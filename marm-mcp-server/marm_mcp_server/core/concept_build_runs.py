import sqlite3
from datetime import datetime, timezone
from typing import Optional


class BuildRunMixin:
    def create_build_run(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: str,
        scope_type: str,
        scope_value: Optional[str],
        created_at: str,
        memories_total: int = 0,
    ) -> None:
        conn.execute(
            """INSERT INTO concept_build_runs
               (id, scope_type, scope_value, status, created_at, memories_total)
               VALUES (?, ?, ?, 'queued', ?, ?)""",
            (run_id, scope_type, scope_value, created_at, memories_total),
        )

    def update_build_run(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        *,
        only_statuses: tuple[str, ...] | None = None,
        require_cancellation: bool | None = None,
        **fields: object,
    ) -> bool:
        allowed = {
            "status",
            "memories_processed",
            "memories_total",
            "entities_extracted",
            "relationships_created",
            "code_links_created",
            "duplicate_candidates",
            "duration_ms",
            "error_code",
            "started_at",
            "last_progress_at",
            "cancel_requested_at",
            "cancelled_at",
            "finished_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return False
        updates.setdefault("last_progress_at", datetime.now(timezone.utc).isoformat())
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conditions = ["id = ?"]
        params: list[object] = [*updates.values(), run_id]
        if only_statuses:
            placeholders = ", ".join("?" for _ in only_statuses)
            conditions.append(f"status IN ({placeholders})")
            params.extend(only_statuses)
        if require_cancellation is True:
            conditions.append("cancel_requested_at IS NOT NULL")
        elif require_cancellation is False:
            conditions.append("cancel_requested_at IS NULL")
        result = conn.execute(
            f"UPDATE concept_build_runs SET {assignments} WHERE {' AND '.join(conditions)}",
            params,
        )
        return result.rowcount > 0

    def get_build_run(self, conn: sqlite3.Connection, run_id: str) -> dict | None:
        row = conn.execute(
            """SELECT id, scope_type, scope_value, status, cancel_requested_at,
                      cancelled_at
               FROM concept_build_runs WHERE id = ?""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "scope_type": row[1],
            "scope_value": row[2],
            "status": row[3],
            "cancel_requested_at": row[4],
            "cancelled_at": row[5],
        }

    def request_build_cancellation(
        self, conn: sqlite3.Connection, run_id: str, requested_at: str
    ) -> tuple[dict | None, bool]:
        result = conn.execute(
            """UPDATE concept_build_runs
               SET cancel_requested_at = COALESCE(cancel_requested_at, ?)
               WHERE id = ? AND status IN ('queued', 'running')""",
            (requested_at, run_id),
        )
        return self.get_build_run(conn, run_id), result.rowcount > 0

    def is_build_cancellation_requested(
        self, conn: sqlite3.Connection, run_id: str
    ) -> bool:
        row = conn.execute(
            "SELECT cancel_requested_at FROM concept_build_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return bool(row and row[0])

    def abandon_unowned_build_runs(
        self, conn: sqlite3.Connection, finished_at: str
    ) -> int:
        """Terminalize build rows only after the caller owns the build lease."""
        result = conn.execute(
            """UPDATE concept_build_runs
               SET status = 'error', error_code = 'stale_run', finished_at = ?
               WHERE status IN ('queued', 'running')""",
            (finished_at,),
        )
        return result.rowcount
