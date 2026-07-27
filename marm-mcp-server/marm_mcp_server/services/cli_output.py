"""Human-readable status/doctor/maintenance rendering for the product CLI."""

from __future__ import annotations

import json
from typing import Any

from ..config.settings import DEFAULT_DB_PATH, SERVER_PORT, SERVER_VERSION


def _print_payload(payload: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(json.dumps(payload, indent=2))


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def _queue_state(queue: dict[str, Any]) -> str:
    if not queue.get("enabled", True):
        return "disabled"
    if queue.get("stopping"):
        return "stopping"
    return "healthy" if queue.get("running") else "starting"


def _print_status(payload: dict[str, Any]) -> None:
    runtime = payload.get("runtime", {})
    metadata = runtime.get("metadata", {})
    mcp = payload.get("mcp", {})
    console = payload.get("console", {})
    memory = payload.get("memory", {})
    knowledge = payload.get("knowledge", {})
    projects = payload.get("projects", {})
    queue = payload.get("write_queue")
    print(f"MARM Memory {payload.get('version', SERVER_VERSION)}")
    print(
        f"Runtime: {runtime.get('state', 'unknown')}"
        f" | profile: {metadata.get('profile', 'standard')}"
    )
    print(
        f"MCP: {mcp.get('state', 'unknown')}"
        f" | http://127.0.0.1:{mcp.get('port', SERVER_PORT)}/mcp"
    )
    print(
        f"Console: {console.get('state', 'unknown')}"
        f" | http://127.0.0.1:{console.get('port', 8002)}"
    )
    if memory.get("error"):
        print(f"Memory: unavailable | {memory['error']}")
    elif memory.get("exists"):
        print(
            f"Memory: {memory.get('memories', 0)} records"
            f" | {memory.get('sessions', 0)} sessions"
            f" | WAL: {memory.get('wal_mode', 'unknown')}"
            f" | {_format_size(memory.get('size_bytes'))}"
        )
    else:
        print(f"Memory: no database at {memory.get('path', DEFAULT_DB_PATH)}")
    if isinstance(queue, dict):
        print(
            f"Write queue: {_queue_state(queue)}"
            f" | depth: {queue.get('depth', queue.get('queue_depth', 0))}"
        )
    else:
        print("Write queue: runtime stopped")
    print(
        f"Knowledge: {knowledge.get('state', 'unknown')}"
        f" | schema: {knowledge.get('schema', 'unknown')}"
    )
    print(f"Projects: {projects.get('state', projects.get('status', 'unknown'))}")


def _print_doctor(payload: dict[str, Any]) -> None:
    print("MARM Doctor")
    for check in payload.get("checks", []):
        marker = (
            "OK" if check.get("ok") else "WARN" if check.get("optional") else "FAIL"
        )
        print(f"[{marker}] {check.get('name')}: {check.get('detail')}")
    retrieval = payload.get("retrieval")
    if isinstance(retrieval, dict):
        print()
        print("Recall tuning")
        print(f"  Keyword match mode: {retrieval.get('fts_query_mode')}")
        print(f"  Keyword candidates: {retrieval.get('fts_candidate_limit')}")
        weight = retrieval.get("hybrid_search_text_weight")
        print(
            f"  Keyword weight: {weight}"
            + (" (keyword matching narrows results only)" if weight == 0 else "")
        )
        extra = retrieval.get("fts_extra_stopwords") or []
        if extra:
            print(f"  Ignored words added: {', '.join(extra)}")
    print()
    _print_status(payload.get("status", {}))


def _print_maintenance(payload: dict[str, Any]) -> None:
    runtime = payload.get("runtime", {})
    memory = payload.get("memory_database", {})
    embedding = payload.get("embedding", {})
    print(f"MARM Maintenance {payload.get('version', SERVER_VERSION)}")
    print(f"Runtime: {runtime.get('state', 'unknown')}")
    queue = runtime.get("write_queue")
    print(
        "Write queue: runtime stopped"
        if not isinstance(queue, dict)
        else f"Write queue: {_queue_state(queue)}"
    )
    print(
        f"Memory DB: {memory.get('path', DEFAULT_DB_PATH)}"
        f" | WAL: {memory.get('wal_mode', 'unknown')}"
        f" | {_format_size(memory.get('size_bytes'))}"
    )
    print(
        f"Embeddings: {'compatible' if embedding.get('compatible') else 'migration required'}"
        f" | {embedding.get('model', 'unknown')}"
    )
