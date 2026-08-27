from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
import sqlite3
import sys
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any

from ..config.settings import (
    CONCEPT_AUTO_INDEX,
    CONCEPT_MODEL_AVAILABLE,
    DEFAULT_DB_PATH,
    DEFAULT_SEMANTIC_MODEL,
    FTS_CANDIDATE_LIMIT,
    FTS_EXTRA_STOPWORDS,
    FTS_LONE_HIT_SCORE,
    FTS_QUERY_MODE,
    HYBRID_SEARCH_TEXT_WEIGHT,
    SEMANTIC_SEARCH_AVAILABLE,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_VERSION,
)
from ..core.concept_db import inspect_concept_schema
from ..core.runtime_manager import inspect_runtime
from ..utils.embedding_state import get_default_concept_db_path, inspect_embedding_state
from ..utils.logging_filters import log_warning_throttled

logger = logging.getLogger(__name__)


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _memory_status(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return result
    try:
        with closing(_read_only(path)) as conn:
            result["wal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            result["memories"] = conn.execute(
                "SELECT COUNT(*) FROM memories"
            ).fetchone()[0]
            result["sessions"] = conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0]
            result["pending_compaction"] = conn.execute(
                "SELECT COUNT(*) FROM compaction_staging "
                "WHERE status IN ('pending_summary', 'summary_staged')"
            ).fetchone()[0]
    except (OSError, sqlite3.Error):
        log_warning_throttled(
            logger, "memory_status", "Memory database status read failed"
        )
        result["error"] = "Could not read the memory database."
    try:
        result["size_bytes"] = path.stat().st_size
    except OSError:
        pass
    return result


def _latest_concept_build(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with closing(_read_only(path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "concept_build_runs" not in tables:
                return None
            row = conn.execute(
                "SELECT id, status, scope_type, scope_value, created_at, finished_at, error_code "
                "FROM concept_build_runs ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    except (OSError, sqlite3.Error):
        return None
    if row is None:
        return None
    keys = (
        "id",
        "status",
        "scope_type",
        "scope_value",
        "created_at",
        "finished_at",
        "error_code",
    )
    return dict(zip(keys, row))


def knowledge_status() -> dict[str, Any]:
    concept_path = Path(get_default_concept_db_path())
    spacy_available = importlib.util.find_spec("spacy") is not None
    model_available = CONCEPT_MODEL_AVAILABLE
    schema = inspect_concept_schema(str(concept_path))
    if not spacy_available:
        state = "missing_spacy"
    elif not model_available:
        state = "missing_model"
    elif schema == "rebuild_required":
        state = "rebuild_required"
    elif schema == "current":
        state = "ready"
    else:
        state = "ready_no_build" if schema == "missing" else "unavailable"
    return {
        "state": state,
        "spacy": spacy_available,
        "model": model_available,
        "schema": schema,
        "auto_index": _concept_auto_index(),
        "index_queue": _index_queue_counts(),
        "database": {"path": str(concept_path), "exists": concept_path.exists()},
        "last_build": _latest_concept_build(concept_path),
    }


def _concept_auto_index() -> bool:
    """The effective switch, not the environment variable. A saved override wins,
    so reporting the env value told the user extraction was on after they had
    turned it off."""
    from ..core import runtime_flags

    return runtime_flags.get_bool(runtime_flags.AUTO_INDEX_CONCEPT, CONCEPT_AUTO_INDEX)


def _index_queue_counts() -> dict[str, Any]:
    """How far behind automatic indexing is. Without this the only symptom of
    a dormant worker is a graph that quietly stops growing.

    None on any failure: a status command must still report the runtime and
    schema even when the memory database cannot be opened.
    """
    try:
        from ..core import concept_queue

        return concept_queue.counts()
    except Exception:
        return {"pending": None, "parked": None}


def maintenance_status() -> dict[str, Any]:
    runtime = inspect_runtime()
    remote = runtime.get("runtime") or {}
    embedding = inspect_embedding_state()
    return {
        "version": SERVER_VERSION,
        "runtime": {
            "state": runtime["state"],
            "write_queue": remote.get("write_queue"),
        },
        "memory_database": _memory_status(Path(DEFAULT_DB_PATH)),
        "concept_database": knowledge_status()["database"],
        "embedding": {
            "model": DEFAULT_SEMANTIC_MODEL,
            "marker": embedding.marker,
            "compatible": embedding.compatible,
            "incompatible_vectors": embedding.incompatible,
            "errors": list(embedding.errors),
        },
    }


def _port_available(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
            return True
        except OSError:
            return False


def _console_status() -> dict[str, Any]:
    host = os.environ.get("MARM_CONSOLE_HOST", "127.0.0.1")
    port = int(os.environ.get("MARM_CONSOLE_PORT", "8002"))
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    try:
        with urllib.request.urlopen(
            f"http://{probe_host}:{port}/health", timeout=0.5
        ) as response:
            payload = json.load(response)
            state = "ready" if payload.get("service") == "marm-console" else "unknown"
    except (urllib.error.URLError, OSError, ValueError):
        state = "stopped"
    return {"host": host, "port": port, "state": state}


def full_status() -> dict[str, Any]:
    runtime = inspect_runtime()
    remote = runtime.get("runtime") or {}
    return {
        "version": SERVER_VERSION,
        "runtime": runtime,
        "mcp": {"host": SERVER_HOST, "port": SERVER_PORT, "state": runtime["state"]},
        "console": _console_status(),
        "memory": _memory_status(Path(DEFAULT_DB_PATH)),
        "write_queue": remote.get("write_queue"),
        "knowledge": knowledge_status(),
        "projects": remote.get("graph", {"state": "runtime_stopped"}),
        "graph_auto_index": _graph_auto_index_status(),
    }


def _graph_auto_index_status() -> dict[str, Any]:
    """The stored switch, readable with no server running.

    Live worker detail (cycles, per-project last-indexed) belongs to whichever
    process owns the loop, so it is not reachable from here.
    """
    from ..config.settings import GRAPH_AUTO_INDEX
    from ..core import runtime_flags

    key = runtime_flags.AUTO_INDEX_GRAPH
    return {
        "enabled": runtime_flags.get_bool(key, GRAPH_AUTO_INDEX),
        "source": runtime_flags.source(key),
        "suppressed_projects": runtime_flags.suppressed_watches(),
        "unindexable_projects": runtime_flags.unindexable_watches(),
    }


def doctor_status() -> dict[str, Any]:
    status = full_status()
    checks = [
        {
            "name": "python",
            "ok": sys.version_info >= (3, 10),
            "detail": "Python 3.10 or newer is required.",
        },
        {
            "name": "memory_database_parent",
            "ok": Path(DEFAULT_DB_PATH).parent.exists()
            and os.access(Path(DEFAULT_DB_PATH).parent, os.W_OK),
            "detail": str(Path(DEFAULT_DB_PATH).parent),
        },
    ]
    runtime_state = status["runtime"]["state"]
    if runtime_state == "stopped":
        checks.append(
            {
                "name": "mcp_port",
                "ok": _port_available(SERVER_HOST, SERVER_PORT),
                "detail": f"{SERVER_HOST}:{SERVER_PORT}",
            }
        )
    checks.extend(
        [
            {
                "name": "embedding_compatibility",
                "ok": maintenance_status()["embedding"]["compatible"],
                "detail": DEFAULT_SEMANTIC_MODEL,
            },
            {
                "name": "knowledge_runtime",
                "ok": status["knowledge"]["state"] in {"ready", "ready_no_build"},
                "detail": status["knowledge"]["state"],
            },
        ]
    )
    return {
        "ok": all(item["ok"] for item in checks if not item.get("optional")),
        "checks": checks,
        "status": status,
        "retrieval": {
            "semantic_search_available": SEMANTIC_SEARCH_AVAILABLE,
            "fts_query_mode": FTS_QUERY_MODE,
            "fts_candidate_limit": FTS_CANDIDATE_LIMIT,
            "hybrid_search_text_weight": HYBRID_SEARCH_TEXT_WEIGHT,
            "fts_lone_hit_score": FTS_LONE_HIT_SCORE,
            "fts_extra_stopwords": sorted(FTS_EXTRA_STOPWORDS),
        },
    }
