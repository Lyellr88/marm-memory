"""Persisted runtime overrides, read through to the environment.

Two things need to outlive a process and be visible to both transports: the
auto-index on/off switches, and the suppressions written when a project is
deleted so a poller cannot resurrect it from a stale cache.

Precedence is deliberate and one way round: a saved override beats the
environment variable. Otherwise a GRAPH_AUTO_INDEX=true baked into a Dockerfile
would silently re-enable something the user turned off, on every restart, with
nothing to show why. `source()` exists so status output can say which one won.
"""

import os
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

AUTO_INDEX_GRAPH = "auto_index.graph"
AUTO_INDEX_CONCEPT = "auto_index.concept"

_SUPPRESS_PREFIX = "watch_suppressed."
_UNINDEXABLE_PREFIX = "unindexable."

_TRUE = "true"
_FALSE = "false"


def _connection() -> Any:
    from .memory import memory

    return memory.get_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get(key: str) -> Optional[str]:
    """The saved value, or None if nothing was ever saved for this key.

    Never raises: a flag read happens on every worker cycle and a missing table
    or a locked database must not stop the cycle, only fall back to the env.
    """
    try:
        with _connection() as conn:
            row = conn.execute(
                "SELECT value FROM runtime_flags WHERE key = ?", (key,)
            ).fetchone()
    except Exception as exc:
        logger.warning("runtime_flags.read_failed", key=key, error=str(exc))
        return None
    return None if row is None else row[0]


def set_(key: str, value: str) -> None:
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO runtime_flags (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, _now()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def clear(key: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM runtime_flags WHERE key = ?", (key,))
    return bool(cursor.rowcount > 0)


def get_bool(key: str, env_default: bool) -> bool:
    saved = get(key)
    if saved is None:
        return env_default
    return saved == _TRUE


def set_bool(key: str, value: bool) -> None:
    set_(key, _TRUE if value else _FALSE)


def source(key: str) -> str:
    """Which layer decides this flag right now: "override" or "environment"."""
    return "environment" if get(key) is None else "override"


# ── Watch suppressions ─────────────────────────────────────────────
# A deleted project must not be re-indexed by a poller still holding it in a
# cached watch set, and a delete issued by another MCP client sharing the engine
# store never notifies MARM at all. The tombstone is durable for that reason,
# and an explicit manual index is what clears it.


def canonical_root(root_path: str) -> str:
    """One spelling per directory, so a tombstone can actually be found again.

    The engine reports root paths with forward slashes ("C:/repo") while MARM's
    own validated paths use the platform separator ("C:\\repo"). Keying on the
    raw string means a manual index never clears the tombstone a delete wrote,
    and the poller keeps skipping a project the user re-indexed. normcase also
    folds case, which matters on Windows for the same reason.
    """
    return os.path.normcase(os.path.normpath(root_path))


def suppress_watch(root_path: str) -> None:
    set_(_SUPPRESS_PREFIX + canonical_root(root_path), _TRUE)


def unsuppress_watch(root_path: str) -> bool:
    return clear(_SUPPRESS_PREFIX + canonical_root(root_path))


def is_watch_suppressed(root_path: str) -> bool:
    return get(_SUPPRESS_PREFIX + canonical_root(root_path)) == _TRUE


# ── Unindexable roots ──────────────────────────────────────────────
# A repository the engine cannot index for a reason that will not change by
# itself, currently only a Windows path length that overflows MAX_PATH. Retrying
# costs the engine gate every cycle and tells the user nothing new.
#
# Durable rather than per-process because the recovery signal cannot be the path.
# The remedy the error suggests, enabling Win32 long paths, fixes the cause while
# leaving the path identical, and it fixes it for both transports at once.


def mark_unindexable(root_path: str, reason: str) -> None:
    set_(_UNINDEXABLE_PREFIX + canonical_root(root_path), reason)


def is_unindexable(root_path: str) -> bool:
    return get(_UNINDEXABLE_PREFIX + canonical_root(root_path)) is not None


def unindexable_watches() -> list[str]:
    return _keys_with_prefix(_UNINDEXABLE_PREFIX)


def clear_index_blocks(root_path: str) -> None:
    """Clear everything that keeps the poller off a root, after a manual index.

    One call rather than two at each of the three manual index paths, so a fourth
    one cannot clear half of it.
    """
    unsuppress_watch(root_path)
    clear(_UNINDEXABLE_PREFIX + canonical_root(root_path))


def _keys_with_prefix(prefix: str) -> list[str]:
    try:
        with _connection() as conn:
            rows = conn.execute(
                "SELECT key FROM runtime_flags WHERE key LIKE ?", (prefix + "%",)
            ).fetchall()
    except Exception as exc:
        logger.warning("runtime_flags.read_failed", error=str(exc))
        return []
    return [row[0][len(prefix) :] for row in rows]


def suppressed_watches() -> list[str]:
    return _keys_with_prefix(_SUPPRESS_PREFIX)
