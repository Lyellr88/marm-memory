"""Lease-backed, coalescing queue for code-link refresh work."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

from ..config.settings import (
    CONCEPT_INDEX_DEBOUNCE_SECONDS,
    CONCEPT_INDEX_LEASE_SECONDS,
    CONCEPT_INDEX_MAX_ATTEMPTS,
)


class ClaimedRefresh(NamedTuple):
    graph_project: str
    memory_project: str
    root_path: str
    cursor_entity_id: int
    enqueued_at: str
    lease_token: str


def _connection() -> Any:
    from .memory import memory

    return memory.get_connection()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(
    conn: sqlite3.Connection, graph_project: str, memory_project: str, root_path: str
) -> None:
    now = _now().isoformat()
    conn.execute(
        """
        INSERT INTO code_link_refresh_queue
            (graph_project, memory_project, root_path, cursor_entity_id, enqueued_at, state, attempts)
        VALUES (?, ?, ?, 0, ?, 'pending', 0)
        ON CONFLICT(graph_project) DO UPDATE SET
            memory_project = excluded.memory_project,
            root_path = excluded.root_path,
            cursor_entity_id = 0,
            enqueued_at = excluded.enqueued_at,
            state = CASE WHEN code_link_refresh_queue.state = 'leased' THEN 'leased' ELSE 'pending' END,
            attempts = CASE WHEN code_link_refresh_queue.state = 'leased' THEN code_link_refresh_queue.attempts ELSE 0 END,
            leased_until = CASE WHEN code_link_refresh_queue.state = 'leased' THEN code_link_refresh_queue.leased_until ELSE NULL END,
            last_error = NULL
        """,
        (graph_project, memory_project, root_path, now),
    )


def enqueue_refresh(graph_project: str, memory_project: str, root_path: str) -> None:
    with _connection() as conn:
        enqueue(conn, graph_project, memory_project, root_path)


def claim(limit: int = 1) -> list[ClaimedRefresh]:
    if limit < 1:
        return []
    now = _now()
    token = uuid.uuid4().hex
    until = (now + timedelta(seconds=CONCEPT_INDEX_LEASE_SECONDS)).isoformat()
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = conn.execute(
                """
                SELECT graph_project, memory_project, root_path, cursor_entity_id, enqueued_at
                FROM code_link_refresh_queue
                WHERE state IN ('pending', 'leased')
                  AND (leased_until IS NULL OR leased_until <= ?)
                ORDER BY enqueued_at
                LIMIT ?
                """,
                (now.isoformat(), limit),
            ).fetchall()
            if not rows:
                conn.execute("COMMIT")
                return []
            projects = [row[0] for row in rows]
            placeholders = ",".join("?" * len(projects))
            conn.execute(
                f"UPDATE code_link_refresh_queue SET state = 'leased', lease_token = ?, leased_until = ? "
                f"WHERE graph_project IN ({placeholders})",
                [token, until, *projects],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return [
        ClaimedRefresh(
            str(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4]), token
        )
        for row in rows
    ]


def renew(graph_projects: Iterable[str], lease_token: str, ttl_seconds: int) -> int:
    projects = list(graph_projects)
    if not projects:
        return 0
    until = (_now() + timedelta(seconds=ttl_seconds)).isoformat()
    placeholders = ",".join("?" * len(projects))
    with _connection() as conn:
        cursor = conn.execute(
            f"UPDATE code_link_refresh_queue SET leased_until = ? "
            f"WHERE graph_project IN ({placeholders}) AND lease_token = ?",
            [until, *projects, lease_token],
        )
    return max(int(cursor.rowcount), 0)


@asynccontextmanager
async def keep_claimed(
    tasks: list[ClaimedRefresh], ttl_seconds: int
) -> AsyncIterator[None]:
    import asyncio

    from .concept_build_lock import heartbeat_interval

    if not tasks:
        yield
        return
    projects = [task.graph_project for task in tasks]
    token = tasks[0].lease_token

    async def _keep_alive() -> None:
        while True:
            await asyncio.sleep(heartbeat_interval(ttl_seconds))
            try:
                await asyncio.to_thread(renew, projects, token, ttl_seconds)
            except Exception:
                pass

    beat = asyncio.create_task(_keep_alive())
    try:
        yield
    finally:
        beat.cancel()
        try:
            await beat
        except (asyncio.CancelledError, Exception):
            pass


def complete(task: ClaimedRefresh) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM code_link_refresh_queue WHERE graph_project = ? "
            "AND lease_token = ? AND enqueued_at = ?",
            (task.graph_project, task.lease_token, task.enqueued_at),
        )
    return bool(cursor.rowcount)


def advance(task: ClaimedRefresh, cursor_entity_id: int) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE code_link_refresh_queue SET cursor_entity_id = ?, state = 'pending', "
            "lease_token = NULL, leased_until = NULL, attempts = 0, last_error = NULL "
            "WHERE graph_project = ? AND lease_token = ? AND enqueued_at = ?",
            (cursor_entity_id, task.graph_project, task.lease_token, task.enqueued_at),
        )
    return bool(cursor.rowcount)


def fail(task: ClaimedRefresh, error: str) -> bool:
    now = _now()
    with _connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT attempts FROM code_link_refresh_queue WHERE graph_project = ? "
                "AND lease_token = ? AND enqueued_at = ?",
                (task.graph_project, task.lease_token, task.enqueued_at),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return False
            attempts = int(row[0]) + 1
            parked = attempts >= CONCEPT_INDEX_MAX_ATTEMPTS
            retry_at = now + timedelta(
                seconds=CONCEPT_INDEX_DEBOUNCE_SECONDS * attempts
            )
            conn.execute(
                "UPDATE code_link_refresh_queue SET attempts = ?, last_error = ?, lease_token = NULL, "
                "leased_until = ?, state = ? WHERE graph_project = ? AND lease_token = ? "
                "AND enqueued_at = ?",
                (
                    attempts,
                    error[:500],
                    None if parked else retry_at.isoformat(),
                    "parked" if parked else "pending",
                    task.graph_project,
                    task.lease_token,
                    task.enqueued_at,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return True


def drop_project(graph_project: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM code_link_refresh_queue WHERE graph_project = ?",
            (graph_project,),
        )
    return bool(cursor.rowcount)


def status(graph_project: str) -> dict[str, object] | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT state, attempts, last_error, enqueued_at FROM code_link_refresh_queue "
            "WHERE graph_project = ?",
            (graph_project,),
        ).fetchone()
    if row is None:
        return None
    return {
        "state": row[0],
        "attempts": int(row[1]),
        "last_error": row[2],
        "enqueued_at": row[3],
    }


def counts() -> dict[str, int]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM code_link_refresh_queue GROUP BY state"
        ).fetchall()
    by_state = {row[0]: int(row[1]) for row in rows}
    return {
        "pending": by_state.get("pending", 0) + by_state.get("leased", 0),
        "parked": by_state.get("parked", 0),
    }
