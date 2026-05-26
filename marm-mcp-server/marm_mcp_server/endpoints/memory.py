"""Memory endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter, Request
from datetime import datetime, timezone

# Import core components
from ..core.models import SmartRecallRequest, ContextLogRequest
from ..core.memory import memory
from ..core.events import events
from ..core.response_limiter import MCPResponseLimiter

# Simple usage tracking function
def track_endpoint_usage(endpoint: str, request: Request, extra_data: dict = None):
    """Track MCP endpoint usage"""
    try:
        import sqlite3
        usage_db = "marm_usage_analytics.db"
        
        user_data = {
            'user_agent': request.headers.get('user-agent', 'unknown'),
            'ip_address': request.client.host if request.client else 'unknown',
            'endpoint': endpoint,
            **(extra_data or {})
        }
        
        with sqlite3.connect(usage_db) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    endpoint TEXT,
                    user_agent TEXT,
                    ip_address TEXT,
                    session_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                INSERT INTO usage_events (timestamp, event_type, endpoint, user_agent, ip_address, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                'endpoint_usage',
                endpoint,
                user_data.get('user_agent'),
                user_data.get('ip_address'),
                str(user_data)
            ))
    except:
        pass  # Don't break MCP if analytics fails

# Create router for memory endpoints
router = APIRouter(prefix="", tags=["Memory"])

@router.post("/marm_smart_recall", operation_id="marm_smart_recall")
async def marm_smart_recall(request: SmartRecallRequest, http_request: Request):
    """
    🧠 Intelligent memory recall based on semantic similarity
    
    Finds relevant memories using semantic similarity or text search.
    Returns the most relevant memories with similarity scores.
    """
    # Track usage
    track_endpoint_usage("marm_smart_recall", http_request, {
        "query_length": len(request.query),
        "session_name": request.session_name,
        "limit": request.limit,
        "search_all": request.search_all
    })
    
    try:
        # Determine which session(s) to search
        search_session = None if request.search_all else request.session_name

        # Run log query up front so it's available in both no_results and success paths.
        # Scope to session_name unless search_all=True, matching memory search behaviour.
        log_results = []
        if request.include_logs:
            with memory.get_connection() as conn:
                if request.search_all:
                    cursor = conn.execute(
                        """
                        SELECT session_name, topic, summary, entry_date
                        FROM log_entries
                        WHERE topic LIKE ? OR summary LIKE ?
                        ORDER BY entry_date DESC
                        LIMIT ?
                        """,
                        (f"%{request.query}%", f"%{request.query}%", request.limit),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT session_name, topic, summary, entry_date
                        FROM log_entries
                        WHERE (topic LIKE ? OR summary LIKE ?) AND session_name = ?
                        ORDER BY entry_date DESC
                        LIMIT ?
                        """,
                        (f"%{request.query}%", f"%{request.query}%", request.session_name, request.limit),
                    )
                log_results = [
                    {"session_name": r[0], "topic": r[1], "summary": r[2], "entry_date": r[3], "type": "log"}
                    for r in cursor.fetchall()
                ]

        similar_memories = await memory.recall_similar(request.query, search_session, request.limit)

        if not similar_memories:
            # If searching all sessions and still no results, check system session specifically
            if not request.search_all:
                # Check if there are results in the system session as a helpful suggestion
                system_memories = await memory.recall_similar(request.query, "marm_system", request.limit)

                response = {
                    "status": "no_results",
                    "query": request.query,
                    "session_name": request.session_name,
                    "search_all": request.search_all,
                    "results": []
                }

                if system_memories:
                    # Found results in system session - provide helpful guidance
                    response["message"] = (
                        f"🤔 No memories found in session '{request.session_name}' for query: '{request.query}'. "
                        f"However, {len(system_memories)} relevant results were found in the system documentation. "
                        f"For future searches, try: marm_smart_recall('{request.query}', session_name='marm_system') "
                        f"or use search_all=True to search across all sessions."
                    )
                    response["suggestion"] = {
                        "try_session": "marm_system",
                        "try_search_all": True,
                        "reason": "System documentation found",
                        "results_count": len(system_memories)
                    }
                else:
                    # No results anywhere - suggest broadening search
                    response["message"] = (
                        f"🤔 No memories found for query: '{request.query}'. "
                        f"Try broadening your query, using session_name='marm_system' for system documentation, "
                        f"or search_all=True to search across all sessions."
                    )

                if request.include_logs:
                    response["log_results"] = log_results
                    response["log_results_count"] = len(log_results)
                return response
            else:
                # Searched all sessions and still no results
                response = {
                    "status": "no_results",
                    "message": f"🤔 No memories found across all sessions for query: '{request.query}'. Try broadening your query.",
                    "query": request.query,
                    "session_name": request.session_name,
                    "search_all": request.search_all,
                    "results": []
                }
                if request.include_logs:
                    response["log_results"] = log_results
                    response["log_results_count"] = len(log_results)
                return response
        
        # Prepare base response metadata
        base_response = {
            "status": "success",
            "message": f"🧠 Found {len(similar_memories)} relevant memories",
            "query": request.query,
            "session_name": request.session_name,
            "search_all": request.search_all,
        }
        
        # Apply MCP size limiting
        limited_memories, was_truncated = MCPResponseLimiter.limit_memory_response(
            similar_memories, base_response
        )
        
        # Format context summary from limited memories
        context_lines = []
        for mem in limited_memories:
            context_lines.append(f"[{mem['context_type'].upper()}] {mem['content']}")
        
        base_response["context_summary"] = "\n".join(context_lines)
        base_response["results"] = limited_memories
        
        # Add truncation notice if needed
        final_response = MCPResponseLimiter.add_truncation_notice(
            base_response, was_truncated, len(similar_memories)
        )

        if request.include_logs:
            final_response["log_results"] = log_results
            final_response["log_results_count"] = len(log_results)

        return final_response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Memory recall failed: {str(e)}")

@router.post("/marm_context_log", operation_id="marm_context_log")
async def marm_context_log(request: ContextLogRequest):
    """
    📝 Log with automatic context classification
    
    Automatically classifies content type and stores with proper context.
    Uses semantic embeddings for intelligent recall.
    """
    try:
        # Sanitize content first
        from ..core.memory import sanitize_content
        sanitized_content = sanitize_content(request.content)

        # Auto-classify and store in memory system (store_memory will also sanitize, but we need sanitized content for response)
        memory_id = await memory.store_memory_queued(request.content, request.session_name)

        # Get the classification that was applied
        context_type = await memory.auto_classify_content(sanitized_content)

        # Emit event for automation system
        await events.emit('memory_stored', {
            'memory_id': memory_id,
            'session': request.session_name,
            'content': sanitized_content,
            'context_type': context_type
        })

        return {
            "status": "success",
            "message": f"📝 Logged and indexed as '{context_type}' context",
            "memory_id": memory_id,
            "content": sanitized_content,
            "session_name": request.session_name,
            "context_type": context_type
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context logging failed: {str(e)}")
