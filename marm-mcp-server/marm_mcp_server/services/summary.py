"""Session summary generation for MARM MCP Server."""

import os
from datetime import datetime, timezone

from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter


def _build_summary_text(rows: list) -> str:
    """Format log_entry rows (entry_date, topic, summary) newest-first into summary text."""
    lines = []
    for entry_date, topic, entry_summary in rows:
        if topic == "session_start":
            lines.append(f"\n## Session: {entry_summary}")
        else:
            s = (
                entry_summary[:197] + "..."
                if len(entry_summary) > 200
                else entry_summary
            )
            lines.append(f"**{entry_date}** [{topic}]: {s}")
    return "\n".join(lines)


async def generate_session_summary(session_name: str) -> dict:
    try:
        with memory.get_connection() as conn:
            total_entries = conn.execute(
                "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
                (session_name,),
            ).fetchone()[0]

            if total_entries == 0:
                return {
                    "status": "empty",
                    "message": f"No entries found in session '{session_name}'",
                }

            cache_row = conn.execute(
                "SELECT summary_text, entry_count, dirty FROM session_summary_cache "
                "WHERE session_name = ?",
                (session_name,),
            ).fetchone()

            cache_clean = (
                cache_row is not None
                and not cache_row[2]
                and cache_row[1] == total_entries
            )

            if cache_clean:
                summary_body = cache_row[0]
            else:
                rows = conn.execute(
                    "SELECT entry_date, topic, summary FROM log_entries "
                    "WHERE session_name = ? ORDER BY entry_date DESC, id DESC",
                    (session_name,),
                ).fetchall()
                summary_body = _build_summary_text(rows)
                now_iso = datetime.now(timezone.utc).isoformat()
                raw_digest = f"{total_entries}:{now_iso}"
                conn.execute(
                    """
                    INSERT INTO session_summary_cache
                        (session_name, raw_digest, summary_text, entry_count, dirty, updated_at)
                    VALUES (?, ?, ?, ?, FALSE, ?)
                    ON CONFLICT(session_name) DO UPDATE SET
                        raw_digest = excluded.raw_digest,
                        summary_text = excluded.summary_text,
                        entry_count = excluded.entry_count,
                        dirty = FALSE,
                        updated_at = excluded.updated_at
                    """,
                    (session_name, raw_digest, summary_body, total_entries, now_iso),
                )

        header = (
            f"# MARM Session Summary: {session_name}\n"
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        )
        full_text = header + summary_body

        result: dict = {
            "status": "success",
            "session_name": session_name,
            "summary": full_text,
            "entry_count": total_entries,
            "total_entries": total_entries,
        }

        if (
            MCPResponseLimiter.estimate_response_size(result)
            > MCPResponseLimiter.CONTENT_LIMIT
        ):
            result["_mcp_truncated"] = True
            result["_truncation_reason"] = "Summary limited to 1MB for MCP compliance"
            lines = full_text.split("\n")
            while (
                len(lines) > 1
                and MCPResponseLimiter.estimate_response_size(result)
                > MCPResponseLimiter.CONTENT_LIMIT
            ):
                lines.pop()
                result["summary"] = "\n".join(lines)
            if (
                MCPResponseLimiter.estimate_response_size(result)
                > MCPResponseLimiter.CONTENT_LIMIT
            ):
                summary = result["summary"]
                low, high = 0, len(summary)
                while low < high:
                    mid = (low + high + 1) // 2
                    result["summary"] = summary[:mid]
                    if (
                        MCPResponseLimiter.estimate_response_size(result)
                        <= MCPResponseLimiter.CONTENT_LIMIT
                    ):
                        low = mid
                    else:
                        high = mid - 1
                result["summary"] = summary[:low]

        if os.environ.get("MARM_SUMMARY_CACHE_DISPOSABLE", "0") == "1":
            try:
                with memory.get_connection() as conn:
                    conn.execute(
                        "DELETE FROM session_summary_cache WHERE session_name = ? AND dirty = FALSE",
                        (session_name,),
                    )
            except Exception:
                pass

        return result

    except Exception as e:
        print(f"Unexpected error in generate_session_summary: {e}")
        return {"status": "error", "message": "Error generating summary."}
