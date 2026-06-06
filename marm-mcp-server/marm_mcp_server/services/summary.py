"""Session summary generation for MARM MCP Server."""

from datetime import datetime

from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter


async def generate_session_summary(session_name: str, limit: int = 50) -> dict:
    try:
        with memory.get_connection() as conn:
            total_entries = conn.execute(
                "SELECT COUNT(*) FROM log_entries WHERE session_name = ?",
                (session_name,),
            ).fetchone()[0]

            entries = conn.execute(
                """
                SELECT entry_date, topic, summary, full_entry
                FROM log_entries WHERE session_name = ?
                ORDER BY entry_date DESC
                LIMIT ?
                """,
                (session_name, limit),
            ).fetchall()

        if not entries:
            return {
                "status": "empty",
                "message": f"No entries found in session '{session_name}'",
            }

        base_response = {
            "status": "success",
            "session_name": session_name,
            "entry_count": 0,
            "total_entries": total_entries,
        }

        summary_lines = [f"# MARM Session Summary: {session_name}"]
        summary_lines.append(
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
        )
        summary_lines.append("")

        if total_entries > len(entries):
            summary_lines.append(
                f"*Showing {len(entries)} most recent entries out of {total_entries} total*"
            )
            summary_lines.append("")

        included_entries = []
        current_lines = summary_lines.copy()

        for entry in entries:
            entry_summary = entry[2]
            if len(entry_summary) > 200:
                entry_summary = entry_summary[:197] + "..."

            entry_line = f"**{entry[0]}** [{entry[1]}]: {entry_summary}"
            test_lines = current_lines + [entry_line]
            test_response = base_response.copy()
            test_response["summary"] = "\n".join(test_lines)

            if (
                MCPResponseLimiter.estimate_response_size(test_response)
                > MCPResponseLimiter.CONTENT_LIMIT
            ):
                break

            current_lines.append(entry_line)
            included_entries.append(entry)

        final_response = {
            "status": "success",
            "session_name": session_name,
            "summary": "\n".join(current_lines),
            "entry_count": len(included_entries),
            "total_entries": total_entries,
        }

        if len(included_entries) < len(entries):
            final_response["_mcp_truncated"] = True
            final_response["_truncation_reason"] = (
                "Summary limited to 1MB for MCP compliance"
            )
            final_response["_entries_shown"] = len(included_entries)
            final_response["_entries_available"] = len(entries)

        return final_response

    except Exception as e:
        return {"status": "error", "message": f"Error generating summary: {str(e)}"}
