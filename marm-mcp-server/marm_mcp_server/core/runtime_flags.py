import os
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

AUTO_INDEX_GRAPH = "auto_index.graph"
AUTO_INDEX_CONCEPT = "auto_index.concept"
RUNTIME_PROFILE = "runtime.profile"
RUNTIME_RATE_LIMIT_RPM = "runtime.rate_limit_rpm"

_SUPPRESS_PREFIX = "watch_suppressed."
_UNINDEXABLE_PREFIX = "unindexable."

_TRUE = "true"
_FALSE = "false"


def _connection() -> Any:
    from .memory import memory

    return memory.get_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(key: str) -> tuple[bool, Optional[str]]:
    """(readable, value). Never raises.

    The two failures have to be told apart. Collapsing them onto None made an
    unreadable database indistinguishable from an unset key, so a locked
    database, which is transient and ordinary, resolved every switch to its
    environment default: a saved "off" would authorize indexing and a deletion
    tombstone would let a poller resurrect the project it protects.
    """
    try:
        with _connection() as conn:
            row = conn.execute(
                "SELECT value FROM runtime_flags WHERE key = ?", (key,)
            ).fetchone()
    except Exception as exc:
        logger.warning("runtime_flags.read_failed", key=key, error=str(exc))
        return False, None
    return True, None if row is None else row[0]


def get(key: str) -> Optional[str]:
    """The saved value, or None for both an unset key and an unreadable one.

    For callers that only display the value. Anything that decides whether work
    may run must use `_read` and fail closed instead.
    """
    return _read(key)[1]


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
    """False when the switch cannot be read, rather than the env default.

    These switches gate background work. An unreadable database is the one case
    where the answer is unknown, and unknown must not authorize a worker to run.
    """
    readable, saved = _read(key)
    if not readable:
        return False
    if saved is None:
        return env_default
    return saved == _TRUE


def set_bool(key: str, value: bool) -> None:
    set_(key, _TRUE if value else _FALSE)


def source(key: str) -> str:
    """Which layer decides this flag right now: "override", "environment", or
    "unknown" when the database could not be read."""
    readable, saved = _read(key)
    if not readable:
        return "unknown"
    return "environment" if saved is None else "override"


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
    """True when the tombstone cannot be read, so an unreadable database cannot
    be the reason a deleted project comes back."""
    readable, value = _read(_SUPPRESS_PREFIX + canonical_root(root_path))
    return True if not readable else value == _TRUE


def mark_unindexable(root_path: str, reason: str) -> None:
    set_(_UNINDEXABLE_PREFIX + canonical_root(root_path), reason)


def unindexable_watches() -> list[str]:
    return _keys_with_prefix(_UNINDEXABLE_PREFIX)


def index_block(root_path: str) -> Optional[str]:
    """Why a poller must leave this root alone right now, or None.

    Both blocks in one query, because the poller has to ask about both on every
    cycle for every project. Checking the tombstone only while reloading the
    watch set left a whole TTL in which the other transport's poller re-indexed
    a project this one had already deleted, recreating it.
    """
    root = canonical_root(root_path)
    suppressed_key = _SUPPRESS_PREFIX + root
    unindexable_key = _UNINDEXABLE_PREFIX + root
    try:
        with _connection() as conn:
            rows = dict(
                conn.execute(
                    "SELECT key, value FROM runtime_flags WHERE key IN (?, ?)",
                    (suppressed_key, unindexable_key),
                ).fetchall()
            )
    except Exception as exc:
        logger.warning("runtime_flags.read_failed", key=root, error=str(exc))
        return "unreadable"
    if rows.get(suppressed_key) == _TRUE:
        return "deleted"
    if unindexable_key in rows:
        return rows[unindexable_key] or "unindexable"
    return None


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


def get_watch_state(root_path: str) -> Optional[dict]:
    """Durable baseline for a root, or None if never recorded or unreadable.

    Never raises and never fabricates a baseline: a database that cannot be
    read must read as "unknown", not as "nothing has changed since the last
    index", or a restart could skip a re-index a project genuinely needs.
    """
    root = canonical_root(root_path)
    try:
        with _connection() as conn:
            row = conn.execute(
                "SELECT source_kind, last_source_state, last_indexed,"
                " last_index_reason, watch_status"
                " FROM graph_watch_state WHERE root_path = ?",
                (root,),
            ).fetchone()
    except Exception as exc:
        logger.warning(
            "runtime_flags.watch_state_read_failed", root=root, error=str(exc)
        )
        return None
    if row is None:
        return None
    return {
        "source_kind": row[0],
        "last_source_state": row[1],
        "last_indexed": row[2],
        "last_index_reason": row[3],
        "watch_status": row[4],
    }


def save_watch_state(
    root_path: str,
    *,
    source_kind: str,
    last_source_state: Optional[str],
    last_indexed: str,
    last_index_reason: str,
    watch_status: str,
) -> None:
    root = canonical_root(root_path)
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO graph_watch_state
                    (root_path, source_kind, last_source_state, last_indexed,
                     last_index_reason, watch_status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(root_path) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    last_source_state = excluded.last_source_state,
                    last_indexed = excluded.last_indexed,
                    last_index_reason = excluded.last_index_reason,
                    watch_status = excluded.watch_status,
                    updated_at = excluded.updated_at
                """,
                (
                    root,
                    source_kind,
                    last_source_state,
                    last_indexed,
                    last_index_reason,
                    watch_status,
                    _now(),
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def saved_runtime_preset() -> tuple[Optional[str], Optional[int]]:
    """Profile and RPM override a Console change persisted, for the next boot to apply."""
    profile = get(RUNTIME_PROFILE)
    raw_rpm = get(RUNTIME_RATE_LIMIT_RPM)
    rpm: Optional[int] = None
    if raw_rpm is not None:
        try:
            rpm = max(0, int(raw_rpm))
        except ValueError:
            logger.warning("Ignoring unreadable saved rate limit", value=raw_rpm)
    return profile, rpm


def save_runtime_preset(profile: str, rate_limit_rpm: Optional[int]) -> None:
    set_(RUNTIME_PROFILE, profile)
    if rate_limit_rpm is None:
        clear(RUNTIME_RATE_LIMIT_RPM)
    else:
        set_(RUNTIME_RATE_LIMIT_RPM, str(max(0, rate_limit_rpm)))
