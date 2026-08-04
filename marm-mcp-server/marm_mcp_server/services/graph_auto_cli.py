"""`projects auto` and `knowledge auto`: the on/off switches for both indexers.

Writes the override straight to the memory database rather than posting to the
running server. Both workers re-read the flag every cycle, so this takes effect
on the next one, and it works whether or not a server is up. `status` reaches for
the live worker detail on top of that, and degrades to the stored flag alone when
nothing is listening.
"""

from typing import Callable, Optional

from ..config import settings
from ..core import runtime_flags


def _describe(key: str, env_default: bool) -> dict:
    return {
        "enabled": runtime_flags.get_bool(key, env_default),
        "source": runtime_flags.source(key),
        "environment_default": env_default,
    }


def dispatch_auto(
    *,
    state: str,
    scope: str,
    print_payload: Callable[..., None],
) -> int:
    """scope is "graph" (projects auto) or "concept" (knowledge auto")."""
    if scope == "graph":
        key = runtime_flags.AUTO_INDEX_GRAPH
        env_default = settings.GRAPH_AUTO_INDEX
    else:
        key = runtime_flags.AUTO_INDEX_CONCEPT
        env_default = settings.CONCEPT_AUTO_INDEX

    if state == "status":
        payload = _describe(key, env_default)
        live = _live_status(scope)
        if live is not None:
            payload["worker"] = live
        print_payload(payload)
        return 0

    runtime_flags.set_bool(key, state == "on")
    payload = _describe(key, env_default)
    payload["effective"] = "next cycle"
    print_payload(payload)
    return 0


def _live_status(scope: str) -> Optional[dict]:
    """Worker detail from an already-running server, or None if none is up.

    Deliberately does not go through the CLI's usual _ensure_runtime, which
    starts a server in the background. Reading a status must never boot one. The
    stored flag is the authority regardless; this only adds cycle counts and
    per-project last-indexed times, which no other process can know.
    """
    if scope != "graph":
        return None
    from ..core.runtime_manager import inspect_runtime, request_runtime_strict

    try:
        if inspect_runtime().get("state") != "ready":
            return None
        result = request_runtime_strict(
            "/marm_graph_index",
            method="POST",
            payload={"action": "auto_status"},
            timeout=10.0,
        )
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    return result.get("auto_index")
