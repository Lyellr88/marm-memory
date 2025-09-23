"""Reasoning endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter, Query
import sqlite3
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Import core components
from core.models import ContextBridgeRequest
from core.memory import memory
from core.events import events
from core.response_limiter import MCPResponseLimiter

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

@router.post("/marm_context_bridge", operation_id="marm_context_bridge")
async def marm_context_bridge(request: ContextBridgeRequest):
    """
    🌉 Intelligent context bridging for smooth workflow transitions
    
    Equivalent to /context_bridge: [new topic] command
    """
    try:
        # Use semantic search for intelligent context bridging
        if memory.encoder:
            # Semantic search across memories for better context matching
            related_memories = await memory.recall_similar(
                query=request.new_topic,
                session=None,  # Search across all sessions
                limit=8
            )
            
            # Also search log entries with basic text matching as backup
            with memory.get_connection() as conn:
                cursor = conn.execute('''
                    SELECT session_name, topic, summary, full_entry
                    FROM log_entries 
                    WHERE topic LIKE ? OR summary LIKE ?
                    ORDER BY entry_date DESC
                    LIMIT 3
                ''', (f"%{request.new_topic}%", f"%{request.new_topic}%"))
                log_matches = cursor.fetchall()
            
            # Combine semantic and text matches
            related_content = []
            for memory_item in related_memories[:5]:
                related_content.append({
                    'type': 'memory',
                    'session': memory_item['session_name'],
                    'content': memory_item['content'],
                    'similarity': memory_item['similarity'],
                    'context_type': memory_item['context_type']
                })
            
            for log_item in log_matches:
                related_content.append({
                    'type': 'log',
                    'session': log_item[0],
                    'topic': log_item[1],
                    'summary': log_item[2],
                    'similarity': 0.7  # Default for text matches
                })
        else:
            # Fallback to basic text search if no semantic search
            with memory.get_connection() as conn:
                cursor = conn.execute('''
                    SELECT session_name, topic, summary, full_entry
                    FROM log_entries 
                    WHERE topic LIKE ? OR summary LIKE ?
                    ORDER BY entry_date DESC
                    LIMIT 5
                ''', (f"%{request.new_topic}%", f"%{request.new_topic}%"))
                log_matches = cursor.fetchall()
                
                related_content = []
                for log_item in log_matches:
                    related_content.append({
                        'type': 'log',
                        'session': log_item[0],
                        'topic': log_item[1],
                        'summary': log_item[2],
                        'similarity': 0.7
                    })
        
        # Prepare base response metadata
        base_response = {
            "status": "success",
            "new_topic": request.new_topic,
            "session_name": request.session_name,
        }
        
        # Apply MCP size limiting to related content first
        limited_content, was_truncated = MCPResponseLimiter.limit_context_bridge_response(
            related_content, base_response
        )
        
        # Build bridge text with limited content
        bridge_lines = [f"# Context Bridge: {request.new_topic}"]
        bridge_lines.append(f"Session: {request.session_name}")
        bridge_lines.append("")
        
        if limited_content:
            bridge_lines.append("## Related Context:")
            # Sort by similarity for better relevance
            sorted_content = sorted(limited_content, key=lambda x: x.get('similarity', 0), reverse=True)
            
            for item in sorted_content:
                similarity_pct = int(item.get('similarity', 0.7) * 100)
                session_badge = f"[{item['session']}]"
                
                if item.get('type') == 'memory':
                    context_badge = f"[{item['context_type'].upper()}]"
                    content_preview = item['content'][:100] + "..." if len(item['content']) > 100 else item['content']
                    truncation_indicator = " [TRUNCATED]" if item.get('_truncated', False) else ""
                    bridge_lines.append(f"- {session_badge} {context_badge} ({similarity_pct}%): {content_preview}{truncation_indicator}")
                else:  # log entry
                    bridge_lines.append(f"- {session_badge} [LOG] ({similarity_pct}%): {item['topic']} - {item['summary']}")
            
            bridge_lines.append("")
            
            # Add truncation notice if content was limited
            if was_truncated:
                bridge_lines.append(f"*Note: Results limited for size compliance. {len(related_content)} total matches found, showing {len(limited_content)}.*")
                bridge_lines.append("")
        
        # Smart recommendations based on limited content found
        if limited_content:
            bridge_lines.append("## Recommended Approach:")
            context_types = [item.get('context_type', 'general') for item in limited_content if item.get('type') == 'memory']
            
            if 'code' in context_types:
                bridge_lines.append("- Review related code patterns and implementations above")
                bridge_lines.append("- Consider lessons learned from similar technical work")
            elif 'project' in context_types:
                bridge_lines.append("- Build on successful project patterns identified above")
                bridge_lines.append("- Apply lessons learned from previous project phases")
            else:
                bridge_lines.append("- Leverage insights from related work shown above")
                bridge_lines.append("- Build on established patterns and approaches")
        else:
            bridge_lines.append("## Starting Fresh:")
            bridge_lines.append("- No directly related context found - starting with clean slate")
            bridge_lines.append("- Consider documenting key decisions as you progress")
        
        bridge_lines.append("")
        bridge_lines.append("---")
        bridge_lines.append("*Ready to proceed with focused work*")
        
        bridge_text = "\n".join(bridge_lines)
        
        final_response = {
            "status": "success",
            "new_topic": request.new_topic,
            "session_name": request.session_name,
            "bridge_text": bridge_text,
            "related_count": len(limited_content),
            "total_available": len(related_content)
        }
        
        # Add truncation notice if needed
        if was_truncated:
            final_response['_mcp_truncated'] = True
            final_response['_truncation_reason'] = "Content limited to 1MB for MCP compliance"
        
        return final_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create context bridge: {str(e)}")
