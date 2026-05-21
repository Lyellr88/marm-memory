"""Reasoning endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter, Query
from datetime import datetime, timezone

# Import core components
from ..core.memory import memory
from ..core.response_limiter import MCPResponseLimiter

# Create router for reasoning endpoints
router = APIRouter(prefix="", tags=["Reasoning"])

@router.get("/marm_summary", operation_id="marm_summary")
async def marm_summary(
    session_name: str = Query(..., description="The name of the session to summarize."),
    limit: int = Query(50, description="Maximum number of entries to include (default: 50)", ge=1, le=200)
):
    """
    📊 Generate paste-ready context block for new chats
    
    Equivalent to /summary: [session name] command
    Uses intelligent truncation to stay within MCP 1MB limits.
    """
    try:
        with memory.get_connection() as conn:
            # Get total count first
            cursor = conn.execute('''
                SELECT COUNT(*) FROM log_entries WHERE session_name = ?
            ''', (session_name,))
            total_entries = cursor.fetchone()[0]
            
            # Get limited entries for summary
            cursor = conn.execute('''
                SELECT entry_date, topic, summary, full_entry
                FROM log_entries WHERE session_name = ?
                ORDER BY entry_date DESC
                LIMIT ?
            ''', (session_name, limit))
            entries = cursor.fetchall()
        
        if not entries:
            return {
                "status": "empty",
                "message": f"No entries found in session '{session_name}'"
            }
        
        # Build base response metadata
        base_response = {
            "status": "success",
            "session_name": session_name,
            "entry_count": len(entries),
            "total_entries": total_entries
        }
        
        # Build summary with size monitoring
        summary_lines = [f"# MARM Session Summary: {session_name}"]
        summary_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
        summary_lines.append("")
        
        if total_entries > len(entries):
            summary_lines.append(f"*Showing {len(entries)} most recent entries out of {total_entries} total*")
            summary_lines.append("")
        
        # Add entries with progressive truncation if needed
        included_entries = []
        current_summary_lines = summary_lines.copy()
        
        for entry in entries:
            # Truncate long summaries to prevent size explosion
            entry_summary = entry[2]
            if len(entry_summary) > 200:
                entry_summary = entry_summary[:197] + "..."
            
            entry_line = f"**{entry[0]}** [{entry[1]}]: {entry_summary}"
            test_lines = current_summary_lines + [entry_line]
            
            # Test response size with this entry added
            test_summary = "\n".join(test_lines)
            test_response = base_response.copy()
            test_response["summary"] = test_summary
            
            response_size = MCPResponseLimiter.estimate_response_size(test_response)
            
            if response_size > MCPResponseLimiter.CONTENT_LIMIT:
                # Can't fit this entry, stop here
                break
            
            # Entry fits, add it
            current_summary_lines.append(entry_line)
            included_entries.append(entry)
        
        summary_text = "\n".join(current_summary_lines)
        
        # Final response with truncation notice if needed
        final_response = {
            "status": "success",
            "session_name": session_name,
            "summary": summary_text,
            "entry_count": len(included_entries),
            "total_entries": total_entries
        }
        
        # Add truncation notice if we couldn't fit all entries
        if len(included_entries) < len(entries):
            final_response["_mcp_truncated"] = True
            final_response["_truncation_reason"] = "Summary limited to 1MB for MCP compliance"
            final_response["_entries_shown"] = len(included_entries)
            final_response["_entries_available"] = len(entries)
        
        return final_response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")
