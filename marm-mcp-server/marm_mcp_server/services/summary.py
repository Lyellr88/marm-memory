"""Session summary generation for MARM MCP Server."""

import os
import uuid
from datetime import datetime, timezone

from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter

_SUMMARY_CACHE_MAX_ENTRIES_PER_CHUNK = 50


def _build_and_cache_chunks(conn, session_name: str) -> list[tuple[str, int]]:
    """Rebuild session_summary_chunks from log_entries. Returns (summary_text, entry_count) oldest-first."""
    rows = conn.execute(
        "SELECT entry_date, topic, summary FROM log_entries "
        "WHERE session_name = ? ORDER BY entry_date ASC, id ASC",
        (session_name,),
    ).fetchall()

    conn.execute(
        "DELETE FROM session_summary_chunks WHERE session_name = ?", (session_name,)
    )

    if not rows:
        return []

    chunk_groups: list[list] = []
    current: list = []
    current_date: str | None = None
    for row in rows:
        entry_date = row[0]
        if current_date is not None and (
            entry_date != current_date
            or len(current) >= _SUMMARY_CACHE_MAX_ENTRIES_PER_CHUNK
        ):
            chunk_groups.append(current)
            current = []
        current_date = entry_date
        current.append(row)
    if current:
        chunk_groups.append(current)

    now_iso = datetime.now(timezone.utc).isoformat()
    result: list[tuple[str, int]] = []

    for i, entries in enumerate(chunk_groups):
        lines = []
        for entry_date, topic, summary in entries:
            if topic == "session_start":
                lines.append(f"\n## Session: {summary}")
            else:
                s = summary[:197] + "..." if len(summary) > 200 else summary
                lines.append(f"**{entry_date}** [{topic}]: {s}")

        summary_text = "\n".join(lines)
        chunk_start = entries[0][0]
        chunk_end = entries[-1][0]
        raw_digest = f"{len(entries)}:{chunk_start}:{chunk_end}"

        conn.execute(
            """
            INSERT INTO session_summary_chunks
                (id, session_name, chunk_index, chunk_start, chunk_end,
                 entry_count, raw_digest, summary_text, dirty, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, FALSE, ?)
            """,
            (
                str(uuid.uuid4()),
                session_name,
                i,
                chunk_start,
                chunk_end,
                len(entries),
                raw_digest,
                summary_text,
                now_iso,
            ),
        )
        result.append((summary_text, len(entries)))

    return result


def _trim_chunk_to_entries(chunk_text: str, max_entries: int) -> tuple[str, int]:
    """Trim pre-formatted chunk text to at most max_entries regular (non-session_start) lines."""
    if max_entries <= 0:
        return "", 0
    lines = chunk_text.split("\n")
    taken = 0
    out = []
    for line in lines:
        if line.startswith("**"):
            if taken >= max_entries:
                break
            taken += 1
        out.append(line)
    return "\n".join(out), taken


def _assemble_summary(
    session_name: str,
    total_entries: int,
    chunks: list[tuple[str, int]],
    limit: int,
) -> dict:
    """Build the marm_summary response from (summary_text, entry_count) chunk pairs (newest first)."""
    header_lines = [
        f"# MARM Session Summary: {session_name}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    base_response = {
        "status": "success",
        "session_name": session_name,
        "entry_count": total_entries,
        "total_entries": total_entries,
    }

    remaining = limit
    included_count = 0
    text_parts: list[str] = []

    for chunk_text, chunk_entry_count in chunks:
        if remaining <= 0:
            break
        if chunk_entry_count > remaining:
            chunk_text, chunk_entry_count = _trim_chunk_to_entries(chunk_text, remaining)
        candidate_parts = text_parts + [chunk_text]
        candidate_summary = "\n".join(header_lines) + "\n" + "\n".join(candidate_parts)
        test_response = {**base_response, "summary": candidate_summary}
        if (
            MCPResponseLimiter.estimate_response_size(test_response)
            > MCPResponseLimiter.CONTENT_LIMIT
        ):
            break
        text_parts.append(chunk_text)
        included_count += chunk_entry_count
        remaining -= chunk_entry_count

    summary_text = "\n".join(header_lines) + "\n" + "\n".join(text_parts)

    final: dict = {
        "status": "success",
        "session_name": session_name,
        "summary": summary_text,
        "entry_count": included_count,
        "total_entries": total_entries,
    }

    if included_count < total_entries:
        final["_mcp_truncated"] = True
        final["_truncation_reason"] = "Summary limited to 1MB for MCP compliance"
        final["_entries_shown"] = included_count
        final["_entries_available"] = total_entries

    return final


async def generate_session_summary(session_name: str, limit: int = 50) -> dict:
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

            row = conn.execute(
                "SELECT COUNT(*) as total, SUM(CASE WHEN dirty THEN 1 ELSE 0 END) as dirty "
                "FROM session_summary_chunks WHERE session_name = ?",
                (session_name,),
            ).fetchone()
            chunk_count, dirty_count = row[0], (row[1] or 0)
            cache_clean = chunk_count > 0 and dirty_count == 0

            if cache_clean:
                cache_rows = conn.execute(
                    "SELECT summary_text, entry_count FROM session_summary_chunks "
                    "WHERE session_name = ? ORDER BY chunk_index DESC",
                    (session_name,),
                ).fetchall()
                chunks = [(r[0], r[1]) for r in cache_rows]
            else:
                chunks = _build_and_cache_chunks(conn, session_name)
                chunks = list(reversed(chunks))

        result = _assemble_summary(session_name, total_entries, chunks, limit)

        if (
            result.get("status") == "success"
            and os.environ.get("MARM_SUMMARY_CACHE_DISPOSABLE", "0") == "1"
        ):
            try:
                with memory.get_connection() as conn:
                    conn.execute(
                        "DELETE FROM session_summary_chunks WHERE session_name = ? AND dirty = FALSE",
                        (session_name,),
                    )
            except Exception:
                pass

        return result

    except Exception as e:
        print(f"Unexpected error in generate_session_summary: {e}")
        return {"status": "error", "message": "Error generating summary."}
