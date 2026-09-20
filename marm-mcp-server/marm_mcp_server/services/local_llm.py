"""An optional, local, OpenAI-compatible generation backend.

MARM has never had a generative model. Concept extraction is spaCy and search
is a sentence encoder, both local, and that is the whole reason `marm_distill`
selects sentences rather than writing them. This module does not change that
default: it makes generation available WHEN a local server happens to be
running, and leaves every caller working when it is not.

WHY LOOPBACK IS ENFORCED AND NOT MERELY DOCUMENTED
    This deployment exists to keep memory on one machine. A configuration
    mistake that pointed this at a hosted endpoint would ship conversation
    transcripts and source code off the box, quietly, with no other symptom.
    So a non-loopback host is refused outright rather than warned about, and
    the refusal names the override -- which requires someone to state the
    intent, in an environment variable, on purpose.

WHY EVERY FAILURE IS A `None` AND NEVER AN EXCEPTION
    The generation path is an enhancement layered over a pipeline that already
    works. A cold model, a busy GPU, a stopped container and a malformed reply
    must all degrade to "no LLM answer this time", because the alternative is a
    memory tool that stops working when an unrelated container is restarted.
    Callers branch on `None`; they do not catch.
"""

from __future__ import annotations

import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator, Optional

import structlog

logger = structlog.get_logger(__name__)

#: Where to look. llama.cpp, Ollama, LM Studio, vLLM and text-generation-webui
#: all speak the same `/v1/chat/completions` shape, so one client covers them.
DEFAULT_URL = os.environ.get("MARM_LLM_URL") or "http://127.0.0.1:18080"

#: Opt-in escape hatch for a non-loopback endpoint. Deliberately verbose.
ALLOW_REMOTE = (
    os.environ.get("MARM_LLM_ALLOW_REMOTE") == "i-understand-this-leaves-my-machine"
)

#: Generation is slower than everything else MARM does, and it is sharing a GPU
#: with whatever else is on the box, so the ceiling is generous but finite.
TIMEOUT = float(os.environ.get("MARM_LLM_TIMEOUT") or 120)

#: Ceiling for the one automatic retry when a model burns its whole budget
#: before answering. Generous enough for a reasoning model's preamble, small
#: enough that a pathological model costs one slow call rather than many.
MAX_RETRY_TOKENS = int(os.environ.get("MARM_LLM_MAX_RETRY_TOKENS") or 8192)

#: A probe is cheap but not free, and the answer changes rarely.
_PROBE_TTL = float(os.environ.get("MARM_LLM_PROBE_TTL") or 60)

#: Keyed by the endpoint as well as the clock. Auto-selection rotates on a
#: 30s TTL while this one defaults to 60s, so without the key a model id
#: probed from server A stayed valid after the endpoint moved to B --
#: and `complete()` then asks B for one of A's models.
_probe_cache: dict[str, Any] = {"at": 0.0, "model": None, "endpoint": None}


def _is_loopback(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


#: The saved on/off switch is read often enough to be worth not hitting SQLite
#: for on every generation call, and changes only when someone clicks it.
_ENABLED_TTL = 5.0
_enabled_cache: dict[str, Any] = {"at": -1.0, "value": True}


def enabled() -> bool:
    """Whether generation is switched on, from the durable runtime flag.

    `get` rather than `get_bool`: `get_bool` answers False when the database
    cannot be read, which is right for the switches that authorise background
    workers and wrong here. Generation is a request someone is waiting on and
    every caller already falls back, so an unreadable database should leave
    the feature where the environment put it, not silently turn it off.
    """
    now = time.monotonic()
    if (now - float(_enabled_cache["at"])) < _ENABLED_TTL:
        return bool(_enabled_cache["value"])
    value = True
    try:
        from ..core import runtime_flags

        saved = runtime_flags.get(runtime_flags.LLM_ENABLED)
        if saved is not None:
            value = saved == "true"
    except Exception:  # pragma: no cover - a flag read must never break a call
        logger.debug("local_llm: could not read the enabled flag")
    _enabled_cache.update({"at": now, "value": value})
    return value


def invalidate_settings_cache() -> None:
    """Drop the cached switch, so a Console toggle takes effect at once."""
    _enabled_cache["at"] = -1.0
    _endpoint_cache["at"] = -1.0
    _probe_cache["at"] = 0.0
    _runtime_cache["at"] = 0.0


def preferred_model() -> Optional[str]:
    """The model the operator chose, when the runtime can honour a choice.

    Returns None on a runtime that ignores the parameter, so a stale
    preference cannot make a caller believe it selected something. See
    `runtime_info` for what that was measured to do.
    """
    try:
        from ..core import runtime_flags

        chosen = runtime_flags.get(runtime_flags.LLM_MODEL)
    except Exception:  # pragma: no cover
        return None
    if not chosen:
        return None
    return chosen if runtime_info().get("can_switch") else None


#: Read on every generation call, so it is cached like the on/off switch.
_ENDPOINT_TTL = 5.0
_endpoint_cache: dict[str, Any] = {"at": -1.0, "value": None}


def _saved_endpoint() -> Optional[str]:
    """The server the operator picked, overriding `MARM_LLM_URL`.

    The environment variable stays the deployment default; this is what the
    Console writes when a different local server is chosen. A saved value that
    is not loopback is ignored the same way the env one is -- the refusal in
    `endpoint()` applies to both, because the point is that nothing leaves the
    machine, not that a particular source is trusted.
    """
    now = time.monotonic()
    if (now - float(_endpoint_cache["at"])) < _ENDPOINT_TTL:
        value = _endpoint_cache["value"]
        return value if isinstance(value, str) else None
    saved = None
    try:
        from ..core import runtime_flags

        saved = runtime_flags.get(runtime_flags.LLM_ENDPOINT) or None
    except Exception:  # pragma: no cover
        logger.debug("local_llm: could not read the saved endpoint")
    _endpoint_cache.update({"at": now, "value": saved})
    return saved


#: Ranked last among live servers: a desktop app is often running with nothing
#: loaded, and this one rejects `response_format={"type":"json_object"}`. Still
#: selected whenever it is the only thing serving.
_DEPRIORITISED_RUNTIMES = ("lm studio",)

_auto_cache: dict[str, Any] = {"at": 0.0, "value": None}
_AUTO_TTL = 30.0


def _explicit_url() -> Optional[str]:
    """An endpoint the operator stated, as opposed to the built-in guess.

    `MARM_LLM_URL` outranks discovery: setting it is a decision, and a decision
    that turns out to name a dead or non-loopback server must SURFACE -- as a
    refusal or a failed probe -- rather than be quietly papered over with
    whatever else happens to be listening. Only the built-in fallback
    (`127.0.0.1:18080`) is superseded by what is actually serving, because that
    one is a guess nobody made.
    """
    return os.environ.get("MARM_LLM_URL") or None


def _chosen_endpoint() -> Optional[str]:
    """An endpoint somebody actually chose -- the Console flag or
    `MARM_LLM_URL` -- as distinct from the built-in guess and from whatever
    auto-selection settled on. One name for the concept, so callers that must
    not re-enter auto-selection have something to ask.
    """
    return _saved_endpoint() or _explicit_url()


def _rank(server: dict[str, Any]) -> tuple:
    """Lower sorts first. Order: has a model, is the deployment default, is not
    a deprioritised runtime, then port for determinism."""
    runtime = str(server.get("runtime") or "").strip().lower()
    url = str(server.get("url") or "").rstrip("/")
    return (
        0 if server.get("model_count") else 1,
        0 if url == DEFAULT_URL.rstrip("/") else 1,
        1 if runtime in _DEPRIORITISED_RUNTIMES else 0,
        int(server.get("port") or 0),
    )


def _auto_endpoint() -> Optional[str]:
    """Whichever local server is actually serving, or None if none is.

    `DEFAULT_URL` was a blind default: it named llama.cpp on 18080 whether or
    not anything was there, so when that container stopped, generation went
    silently off for 22 hours while LM Studio was serving on 1234 the whole
    time. Here the default becomes a *preference* -- first choice when it
    answers, ignored when it does not.

    Cached separately from the saved-endpoint lookup because a scan is nine
    connect() calls rather than one flag read; a closed loopback port refuses
    instantly, so the sweep is milliseconds, but not per generation.
    """
    now = time.monotonic()
    if (now - float(_auto_cache["at"])) < _AUTO_TTL:
        value = _auto_cache["value"]
        return value if isinstance(value, str) else None
    chosen = None
    try:
        servers = (discover_servers() or {}).get("servers") or []
        # Filter here rather than letting `endpoint()` refuse: a refusal there
        # returns None and turns generation off completely, so one bad entry
        # would cost the working servers too. Discovery only scans 127.0.0.1,
        # so this is a guard against a future caller, not a live case.
        live = [
            s
            for s in servers
            if s.get("url") and (_is_loopback(str(s["url"])) or ALLOW_REMOTE)
        ]
        if live:
            chosen = str(sorted(live, key=_rank)[0]["url"]).rstrip("/")
    except Exception:  # pragma: no cover - discovery must never break generation
        logger.debug("local_llm: auto-selection failed; falling back to the default")
    _auto_cache.update({"at": now, "value": chosen})
    return chosen


def endpoint_source() -> str:
    """Which rule produced the endpoint: flag, environment, discovery, default.

    Worth reporting because the four are not equally trustworthy and a reader
    cannot tell them apart from the URL alone. "discovery" in particular means
    *this can change by itself* when a server starts or stops, which is the
    whole point of auto-selection and exactly the thing a person staring at a
    settings pane would otherwise have to guess at.
    """
    if _saved_endpoint():
        return "flag"
    if _explicit_url():
        return "environment"
    if _auto_endpoint():
        return "discovery"
    return "default"


def endpoint() -> Optional[str]:
    """The endpoint to use, or None when it must not be used.

    Resolution order: the operator's explicit pick, then whatever is actually
    serving, then the configured default. Auto-selection sits in the middle on
    purpose -- a Console choice is a decision and must not be overridden, while
    the default is only a starting guess.

    Deliberately NOT gated on `enabled()`. The switch belongs in `available()`
    instead: the Console has to keep probing which runtime and model are there
    in order to render the pane you turn generation back on from, and gating
    here would blank that pane at exactly the moment it is being read.
    """
    url = (_chosen_endpoint() or _auto_endpoint() or DEFAULT_URL).rstrip("/")
    if not url:
        return None
    if not _is_loopback(url) and not ALLOW_REMOTE:
        logger.warning(
            "local_llm: refusing a non-loopback endpoint",
            url=url,
            override="MARM_LLM_ALLOW_REMOTE",
        )
        return None
    return url


def _request(path: str, payload: Optional[dict], timeout: float) -> Optional[dict]:
    base = endpoint()
    if base is None:
        return None
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode())
        return decoded if isinstance(decoded, dict) else None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        logger.debug("local_llm: request failed", path=path, error=str(exc))
        return None


def available(force: bool = False) -> Optional[str]:
    """Return the served model id, or None. Cached for `_PROBE_TTL` seconds.

    A negative result is cached too. Without that, every distil run on a
    machine with no model pays a full connection timeout before falling back,
    which turns a working feature into a slow one.

    This is also where the operator's on/off switch lands, because it is the
    check every caller already makes before reaching for a model. Switched
    off reads as "no model is available", which is a state every path was
    already written to handle.
    """
    if not enabled():
        return None
    now = time.monotonic()
    base = endpoint()
    if (
        not force
        and _probe_cache["endpoint"] == base
        and (now - float(_probe_cache["at"])) < _PROBE_TTL
    ):
        cached = _probe_cache["model"]
        return cached if isinstance(cached, str) else None

    body = _request("/v1/models", None, timeout=5.0)
    model = None
    if isinstance(body, dict):
        entries = body.get("data") or body.get("models") or []
        if entries and isinstance(entries, list):
            served = [
                e.get("id") or e.get("name")
                for e in entries
                if isinstance(e, dict) and (e.get("id") or e.get("name"))
            ]
            # Honour the operator's choice when the server is actually serving
            # it. Without this the saved preference was display-only: every
            # completion used entries[0], so picking a model in the Console
            # reported a switch that never happened.
            wanted = preferred_model()
            model = (
                wanted
                if wanted and wanted in served
                else (served[0] if served else None)
            )
    _probe_cache["at"] = now
    _probe_cache["model"] = model
    _probe_cache["endpoint"] = base
    return model


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: Optional[float] = None,
    json_object: bool = False,
    _retrying: bool = False,
) -> Optional[str]:
    """One turn of chat completion. Returns the text, or None on any failure.

    `temperature` defaults to 0 because every caller here is doing extraction
    or grounded answering, where the same input should give the same output --
    a memory proposal that changes between two runs over one transcript is not
    a proposal a reviewer can act on.
    """
    model = available()
    if model is None:
        return None

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}

    body = _request("/v1/chat/completions", payload, timeout or TIMEOUT)
    if body is None and json_object:
        # `json_object` is an optimisation, not a requirement -- callers parse
        # defensively anyway. LM Studio REJECTS it outright: measured against
        # 0.3.x, `{"type":"json_object"}` returns HTTP 400
        # "'response_format.type' must be 'json_schema' or 'text'", so every
        # generated distillation silently fell back to sentence selection the
        # moment MARM pointed at LM Studio instead of llama.cpp. Retrying
        # without it costs one request on servers that refuse, and nothing on
        # servers that do not.
        payload.pop("response_format", None)
        body = _request("/v1/chat/completions", payload, timeout or TIMEOUT)
    if not isinstance(body, dict):
        return None
    try:
        choice = body["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        logger.debug("local_llm: unexpected response shape")
        return None
    if isinstance(text, str) and text.strip():
        return text.strip()

    # Empty content is not an empty answer. A reasoning model (gpt-oss, the
    # R1 family) emits its chain of thought into a separate `reasoning` field
    # and can spend the whole token budget there, returning
    # finish_reason="length" with content still "". Returning "" would hand
    # the caller a confident blank; None is the state every caller already
    # falls back from.
    if choice.get("finish_reason") == "length" and not _retrying:
        # A reasoning model can spend its whole budget in `reasoning` and
        # return content="", and auto-selection means the model can change
        # underneath this call -- so coping belongs here, not in each caller's
        # constant. One retry, quadrupled and capped: a model that cannot
        # answer in 4x its budget is not going to.
        wider = min(max_tokens * 4, MAX_RETRY_TOKENS)
        if wider > max_tokens:
            logger.debug(
                "local_llm: retrying with a wider token budget",
                model=model,
                was=max_tokens,
                now=wider,
            )
            return complete(
                system,
                user,
                max_tokens=wider,
                temperature=temperature,
                timeout=timeout,
                json_object=json_object,
                _retrying=True,
            )
    if choice.get("finish_reason") == "length":
        logger.debug(
            "local_llm: the model hit the token limit before answering",
            model=model,
            hint="the retry at a wider budget also came back empty",
        )
    return None


def stream(
    system: str,
    user: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: Optional[float] = None,
) -> Iterator[str]:
    """Yield the reply in pieces as the model produces them.

    Total time is the same as `complete`; what changes is that a reader sees
    text at the first token instead of nothing until the last.

    Deliberately unused by the MCP tool: an agent consumes the whole answer
    before acting on any of it, so the tool keeps returning one JSON body.

    Yields nothing at all when no model is reachable -- the same degradation
    `complete` makes, in the shape a `for` loop already handles.
    """
    base = endpoint()
    model = available()
    if base is None or model is None:
        return

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    request = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout or TIMEOUT) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    return
                try:
                    chunk = json.loads(body)
                except ValueError:
                    continue
                choices = chunk.get("choices") or [{}]
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        # A stream that dies mid-answer has already yielded real text, so the
        # caller keeps what arrived rather than losing the answer to a
        # truncated connection. Logged, not raised, like every other failure.
        logger.debug("local_llm: stream failed", error=str(exc))
        return


def complete_json(
    system: str, user: str, *, max_tokens: int = 2048, timeout: Optional[float] = None
) -> Optional[Any]:
    """`complete`, then parse JSON out of the reply.

    Models wrap JSON in prose and fences however they were tuned to, so this
    recovers the first balanced object or array rather than trusting the reply
    to be clean. A model that cannot be parsed is a model that did not answer,
    which is the same `None` as no model at all.
    """
    text = complete(
        system, user, max_tokens=max_tokens, timeout=timeout, json_object=True
    )
    if not text:
        return None
    return _first_json_value(text)


def _first_json_value(text: str) -> Optional[Any]:
    """Recover the first JSON object or array embedded in `text`."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1] if "```" in stripped[3:] else stripped[3:]
        if stripped.lstrip().lower().startswith("json"):
            stripped = stripped.lstrip()[4:]
    try:
        return json.loads(stripped)
    except ValueError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char in "[{":
            try:
                value, _ = decoder.raw_decode(stripped[index:])
                return value
            except ValueError:
                continue
    return None


def _get_at(base: str, path: str, timeout: float = 4.0) -> Optional[dict]:
    """GET a diagnostic path on an arbitrary loopback base URL."""
    try:
        request = urllib.request.Request(f"{base}{path}", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
        return body if isinstance(body, dict) else None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


def _get(path: str, timeout: float = 4.0) -> Optional[dict]:
    """GET a diagnostic path, tolerating a runtime that does not serve it.

    `_request` cannot be reused: it reports only that something failed, and
    here the difference between "404, so this is not llama.cpp" and "nothing
    is listening" is most of the answer.
    """
    base = endpoint()
    if base is None:
        return None
    try:
        request = urllib.request.Request(f"{base}{path}", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
        return body if isinstance(body, dict) else None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


#: Which server is running changes far less often than whether it answers.
_RUNTIME_TTL = float(os.environ.get("MARM_LLM_RUNTIME_TTL") or 30.0)

#: Endpoint-keyed for the same reason as `_probe_cache`: `can_switch`,
#: `model_path` and `served` all describe one server.
_runtime_cache: dict[str, Any] = {"at": 0.0, "value": None, "endpoint": None}


def _identify(base: Optional[str], timeout: float = 4.0) -> dict[str, Any]:
    """Which server answers at `base`, and whether it can change models.

    Pure: no caching, no reference to the configured endpoint. That is what
    lets `discover_servers` reuse it against every candidate port instead of
    keeping a second, drifting copy of the detection rules.
    """
    info: dict[str, Any] = {
        "runtime": None,
        "version": None,
        "can_switch": False,
        "model_path": None,
        "context_length": None,
        "served": [],
        "reason": None,
    }

    props = _get_at(base, "/props", timeout) if base else None
    if isinstance(props, dict) and "model_path" in props:
        generation = props.get("default_generation_settings")
        alias = props.get("model_alias")
        info.update(
            {
                "runtime": "llama.cpp",
                "model_path": props.get("model_path"),
                "context_length": (
                    generation.get("n_ctx") if isinstance(generation, dict) else None
                ),
                "can_switch": False,
                "served": (
                    [{"id": alias, "path": props.get("model_path")}] if alias else []
                ),
                "reason": (
                    "llama.cpp serves one model per process and ignores the model "
                    "parameter, so MARM cannot switch it from here. Restart "
                    "llama-server with a different -m to change it."
                ),
            }
        )
        return info

    tags = _get_at(base, "/api/tags", timeout) if base else None
    if isinstance(tags, dict) and isinstance(tags.get("models"), list):
        version = (_get_at(base, "/api/version", timeout) if base else None) or {}
        info.update(
            {
                "runtime": "Ollama",
                "version": version.get("version"),
                "can_switch": True,
                "served": [
                    {"id": m.get("name") or m.get("model"), "path": None}
                    for m in tags["models"]
                    if isinstance(m, dict)
                ],
            }
        )
        return info

    lmstudio = _get_at(base, "/api/v0/models", timeout) if base else None
    if isinstance(lmstudio, dict) and isinstance(lmstudio.get("data"), list):
        info.update(
            {
                "runtime": "LM Studio",
                "can_switch": True,
                "served": [
                    {"id": m.get("id"), "path": m.get("path"), "state": m.get("state")}
                    for m in lmstudio["data"]
                    if isinstance(m, dict)
                ],
            }
        )
        return info

    body = _get_at(base, "/v1/models", timeout) if base else None
    if isinstance(body, dict):
        entries = body.get("data") or body.get("models") or []
        served = [
            {"id": e.get("id") or e.get("name"), "path": None}
            for e in entries
            if isinstance(e, dict)
        ]
        info.update(
            {
                "runtime": "OpenAI-compatible",
                "served": served,
                "can_switch": len(served) > 1,
                "reason": (
                    None
                    if len(served) > 1
                    else "This server lists a single model, so there is nothing to "
                    "switch to. MARM does not assume an unlisted model can load."
                ),
            }
        )
    return info


def runtime_info(force: bool = False) -> dict[str, Any]:
    """Which server is on the other end, and whether it can change models.

    A model dropdown would otherwise lie on llama.cpp: it serves one model per
    process and ignores the `model` parameter, answering a request for a
    non-existent model with HTTP 200 and no error field. A UI that set it would
    report a switch that never happened.

    So the runtime is identified first and `can_switch` is derived from what
    that runtime actually does, never assumed:

      llama.cpp   `/props` answers with `model_path`. One model per process,
                  so switching means restarting a server MARM does not own.
      Ollama      `/api/tags` lists what is pulled and it loads on demand, so
                  naming a model in the request genuinely selects it.
      LM Studio   `/api/v0/models` carries per-model `state` and JIT-loads,
                  so the same holds.
      other       an OpenAI-compatible server listing more than one model is
                  taken at its word; one listed model is treated as fixed.
    """
    now = time.monotonic()
    base = endpoint()
    cached = _runtime_cache["value"]
    if (
        not force
        and cached is not None
        and _runtime_cache["endpoint"] == base
        and (now - float(_runtime_cache["at"])) < _RUNTIME_TTL
    ):
        return dict(cached)

    info = _identify(base)
    _runtime_cache.update({"at": now, "value": info, "endpoint": base})
    return dict(info)


def status() -> dict[str, Any]:
    """What the Console shows so a user knows whether generation is on."""
    base = endpoint()
    on = enabled()
    # Probe regardless of the switch: the pane that turns generation back on
    # has to say what it would turn on, so "off" must not also mean "unknown".
    info = runtime_info() if base else {}
    model = (available(force=True) if on else None) if base else None
    return {
        "configured": bool(base),
        "enabled": on,
        "endpoint": base,
        "available": model is not None,
        "model": model or (info.get("served") or [{}])[0].get("id"),
        "model_in_use": model,
        "preferred_model": preferred_model(),
        "loopback_enforced": not ALLOW_REMOTE,
        "runtime": info.get("runtime"),
        "runtime_version": info.get("version"),
        "can_switch": bool(info.get("can_switch")),
        "model_path": info.get("model_path"),
        "context_length": info.get("context_length"),
        "served": info.get("served") or [],
        "switch_blocked_reason": info.get("reason"),
        "endpoint_source": endpoint_source(),
    }


#: Where the popular local servers listen, with the name each is known by.
#: Ports, not processes: MARM cannot see what is running, only what answers,
#: and a server moved to another port is found by adding it as a custom URL.
KNOWN_PORTS: tuple[tuple[int, str], ...] = (
    (1234, "LM Studio"),
    (11434, "Ollama"),
    (8000, "vLLM"),
    (8080, "llama.cpp / LocalAI"),
    (1337, "Jan"),
    (5001, "KoboldCpp"),
    (5000, "text-generation-webui"),
    (4891, "GPT4All"),
    (18080, "llama.cpp"),
)

#: A closed loopback port refuses instantly, so this only bounds the case where
#: something IS listening and is not an LLM server.
_SCAN_CONNECT_TIMEOUT = 0.25
_SCAN_HTTP_TIMEOUT = 1.5

_servers_cache: dict[str, Any] = {"at": 0.0, "value": None}
_SERVERS_TTL = 15.0


def _marm_own_ports() -> set[int]:
    """Ports MARM itself serves, which must never be probed.

    Asking yourself a question over HTTP from the loop that would answer it
    deadlocks until the timeout -- the same defect that made
    `/internal/runtime/settings` take a full second. A scan that included them
    would reintroduce it once per sweep.
    """
    ports = set()
    for name, fallback in (("SERVER_PORT", 8001), ("MARM_CONSOLE_PORT", 8002)):
        try:
            ports.add(int(os.environ.get(name) or fallback))
        except ValueError:
            ports.add(fallback)
    return ports


def _port_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(_SCAN_CONNECT_TIMEOUT)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _probe_server(port: int, label: str) -> Optional[dict[str, Any]]:
    """Identify whatever answers on a loopback port, or None."""
    if not _port_open(port):
        return None
    base = f"http://127.0.0.1:{port}"
    info = _identify(base, timeout=_SCAN_HTTP_TIMEOUT)
    if not info or not info.get("runtime"):
        # Something is listening and it is not an LLM server -- syncthing and
        # a dozen other things live on these ports too. Reporting it as a
        # candidate would offer the reader an endpoint that cannot generate.
        return None
    served = info.get("served") or []
    return {
        "url": base,
        "port": port,
        "expected": label,
        "runtime": info.get("runtime"),
        "version": info.get("version"),
        "can_switch": bool(info.get("can_switch")),
        "model_count": len(served),
        "models": [entry.get("id") for entry in served if entry.get("id")][:20],
        "model_path": info.get("model_path"),
        "context_length": info.get("context_length"),
    }


def discover_servers(force: bool = False) -> dict[str, Any]:
    """Every local OpenAI-compatible server this machine is running.

    Loopback only -- the same rule `endpoint()` enforces; nothing that is not
    127.0.0.1 is ever probed.

    The configured endpoint is always included even on an unknown port, so that
    "the one you configured is dead" can be reported.
    """
    now = time.monotonic()
    cached = _servers_cache["value"]
    if (
        not force
        and cached is not None
        and (now - float(_servers_cache["at"])) < _SERVERS_TTL
    ):
        return dict(cached)

    skip = _marm_own_ports()
    candidates: list[tuple[int, str]] = [
        (port, label) for port, label in KNOWN_PORTS if port not in skip
    ]

    # NOT `endpoint()`: that consults auto-selection, which consults this
    # function -- mutual recursion. What belongs here is the endpoint somebody
    # CONFIGURED; an auto-selected one is by construction already discovered.
    configured = _chosen_endpoint() or DEFAULT_URL
    configured_port = None
    if configured:
        try:
            configured_port = urllib.parse.urlparse(configured).port
        except ValueError:
            configured_port = None
    if configured_port and configured_port not in {p for p, _ in candidates}:
        if configured_port not in skip:
            candidates.append((configured_port, "configured"))

    # Extra ports an operator names, for a server on an unusual port.
    for raw in (os.environ.get("MARM_LLM_SCAN_PORTS") or "").split(","):
        raw = raw.strip()
        if raw.isdigit() and int(raw) not in skip:
            candidates.append((int(raw), "configured"))

    started = time.monotonic()
    found: list[dict[str, Any]] = []
    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(8, len(candidates) or 1)) as pool:
            for result in pool.map(lambda c: _probe_server(*c), candidates):
                if result:
                    found.append(result)
    except Exception:  # pragma: no cover - a scan must never escape
        logger.exception("local_llm: scanning for servers raised")

    found.sort(key=lambda s: (s["url"] != configured, s["port"]))
    value = {
        "servers": found,
        "configured": configured,
        "configured_reachable": any(s["url"] == configured for s in found),
        "scanned_ports": [port for port, _ in candidates],
        "scan_seconds": round(time.monotonic() - started, 3),
    }
    _servers_cache.update({"at": now, "value": value})
    return dict(value)


def invalidate_servers_cache() -> None:
    _servers_cache["at"] = 0.0
    _servers_cache["value"] = None
