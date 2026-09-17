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

#: A probe is cheap but not free, and the answer changes rarely.
_PROBE_TTL = float(os.environ.get("MARM_LLM_PROBE_TTL") or 60)

_probe_cache: dict[str, Any] = {"at": 0.0, "model": None}


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


def endpoint() -> Optional[str]:
    """The configured endpoint, or None when it must not be used.

    Deliberately NOT gated on `enabled()`. The switch belongs in `available()`
    instead: the Console has to keep probing which runtime and model are there
    in order to render the pane you turn generation back on from, and gating
    here would blank that pane at exactly the moment it is being read.
    """
    url = DEFAULT_URL.rstrip("/")
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
    if not force and (now - float(_probe_cache["at"])) < _PROBE_TTL:
        cached = _probe_cache["model"]
        return cached if isinstance(cached, str) else None

    body = _request("/v1/models", None, timeout=5.0)
    model = None
    if isinstance(body, dict):
        entries = body.get("data") or body.get("models") or []
        if entries and isinstance(entries, list):
            first = entries[0]
            model = (
                first.get("id") or first.get("name")
                if isinstance(first, dict)
                else None
            )
    _probe_cache["at"] = now
    _probe_cache["model"] = model
    return model


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: Optional[float] = None,
    json_object: bool = False,
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
        # Honoured by llama.cpp, vLLM and LM Studio; ignored by servers that do
        # not implement it, which is why callers must still parse defensively.
        payload["response_format"] = {"type": "json_object"}

    body = _request("/v1/chat/completions", payload, timeout or TIMEOUT)
    if not isinstance(body, dict):
        return None
    try:
        text = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        logger.debug("local_llm: unexpected response shape")
        return None
    return text.strip() if isinstance(text, str) else None


def stream(
    system: str,
    user: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    timeout: Optional[float] = None,
) -> Iterator[str]:
    """Yield the reply in pieces as the model produces them.

    WHY THIS EXISTS AT ALL, GIVEN `complete` WORKS
        Measured on this machine: a grounded answer takes 8.6 s, and the first
        token arrives at 282 ms. Non-streaming spends 8.3 of those seconds
        showing a reader nothing, which reads as a hung page rather than a slow
        one. The total time is identical; what changes is whether anything is
        happening on screen.

    WHY IT IS NOT USED BY THE MCP TOOL
        An agent consumes the whole answer before it acts on any of it, so
        streaming to an agent adds framing and buys nothing. This is a
        human-interface concern, and the tool keeps returning one JSON body.

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

_runtime_cache: dict[str, Any] = {"at": 0.0, "value": None}


def runtime_info(force: bool = False) -> dict[str, Any]:
    """Which server is on the other end, and whether it can change models.

    THIS EXISTS BECAUSE A MODEL DROPDOWN IS A LIE ON llama.cpp. Measured
    2026-09-17 against the live endpoint: a request naming
    `definitely-not-a-real-model` was answered by `qwen3.6-27b-mtp` with HTTP
    200 and no error field. llama-server serves one model per process and
    ignores the `model` parameter, so a UI that set it would report success,
    change nothing, and give the reader no way to find out.

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
    cached = _runtime_cache["value"]
    if (
        not force
        and cached is not None
        and (now - float(_runtime_cache["at"])) < _RUNTIME_TTL
    ):
        return dict(cached)

    info: dict[str, Any] = {
        "runtime": None,
        "version": None,
        "can_switch": False,
        "model_path": None,
        "context_length": None,
        "served": [],
        "reason": None,
    }

    props = _get("/props")
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
        _runtime_cache.update({"at": now, "value": info})
        return dict(info)

    tags = _get("/api/tags")
    if isinstance(tags, dict) and isinstance(tags.get("models"), list):
        version = _get("/api/version") or {}
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
        _runtime_cache.update({"at": now, "value": info})
        return dict(info)

    lmstudio = _get("/api/v0/models")
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
        _runtime_cache.update({"at": now, "value": info})
        return dict(info)

    body = _get("/v1/models")
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
    _runtime_cache.update({"at": now, "value": info})
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
    }
