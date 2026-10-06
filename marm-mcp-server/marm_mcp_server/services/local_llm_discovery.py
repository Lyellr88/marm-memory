from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, Optional

import structlog

from .local_llm_wire import _is_loopback

logger = structlog.get_logger(__name__)


def _get_at(base: str, path: str, timeout: float = 4.0) -> Optional[dict]:
    """GET a diagnostic path on an arbitrary loopback base URL."""
    try:
        request = urllib.request.Request(f"{base}{path}", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
        return body if isinstance(body, dict) else None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return None


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


def _is_marm_itself(url: str) -> bool:
    try:
        port = urllib.parse.urlparse(url).port
    except ValueError:
        return False
    return port in _marm_own_ports() and _is_loopback(url)


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


def discover_servers(
    configured_endpoint: Callable[[], Optional[str]], force: bool = False
) -> dict[str, Any]:
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
    configured = configured_endpoint()
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
