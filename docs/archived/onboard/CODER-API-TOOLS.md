# MARM Systems - API Tools & Database Guide

**Version**: 2.2.5 | **Focus**: MCP tools, endpoints, database schema | **Lines**: ~280

---

## Complete MCP Tool Suite

The MARM server exposes MCP tools organized by category:

### 🧠 Memory Intelligence

- `marm_smart_recall` - Semantic similarity search with fallback
- `marm_contextual_log` - Auto-classifying memory storage

### 🚀 Session Management

- `marm_start` - Activate MARM protocol
- `marm_refresh` - Refresh session state

### 📚 Logging System

- `marm_log_session` - Create/switch session containers
- `marm_log_entry` - Add structured log entries
- `marm_log_show` - Display logs with filtering
- `marm_log_delete` - Delete sessions/entries

### 🔄 Reasoning & Workflow

- `marm_summary` - Generate context-aware summaries
- `marm_context_bridge` - Smart workflow transitions

### 📔 Notebook Management

- `marm_notebook_add` - Add entries with embeddings
- `marm_notebook_use` - Activate entries as instructions
- `marm_notebook_show` - Display all entries
- `marm_notebook_delete` - Delete specific entries
- `marm_notebook_clear` - Clear active instructions
- `marm_notebook_status` - Show active instruction list

### ⚙️ System Utilities

- `marm_current_context` - Automatic date/time context
- `marm_system_info` - Health status and diagnostics

---

## HTTP Endpoints

All MCP tools are accessible via HTTP POST to `/[tool_name]`:

```bash
# Example: Smart recall
POST http://localhost:8001/marm_smart_recall
{
  "query": "authentication bug",
  "session_name": "main",
  "limit": 5,
  "search_all": false
}

# Health check
GET http://localhost:8001/health

# API documentation
GET http://localhost:8001/docs
```

### WebSocket Support (Production parity)

Full HTTP/WebSocket parity with JSON-RPC 2.0:

```javascript
// Connect to WebSocket
ws://localhost:8001/mcp/ws

// Example request
{
  "jsonrpc": "2.0",
  "method": "marm_smart_recall",
  "params": {
    "query": "authentication bug",
    "session_name": "main"
  },
  "id": 1
}
```

---

## Database Schema & Models

### Core Tables

#### `memories` - Central memory storage

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,              -- Vector embeddings for semantic search
    timestamp TEXT NOT NULL,
    context_type TEXT DEFAULT 'general',  -- Auto-classified: code, project, book, general
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `sessions` - Session management

```sql
CREATE TABLE sessions (
    session_name TEXT PRIMARY KEY,
    marm_active BOOLEAN DEFAULT FALSE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_accessed TEXT DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT DEFAULT '{}'
);
```

#### `log_entries` - Structured logging

```sql
CREATE TABLE log_entries (
    id TEXT PRIMARY KEY,
    session_name TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    full_entry TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `notebook_entries` - Knowledge management

```sql
CREATE TABLE notebook_entries (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    embedding BLOB,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `user_settings` - Configuration storage

```sql
CREATE TABLE user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### Connection Pool Architecture

MARM uses a custom SQLite connection pool for performance:

```python
class SQLiteConnectionPool:
    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self.pool = queue.Queue(maxsize=max_connections)
        # WAL mode, optimized cache settings
```

Key optimizations:

- **WAL Mode**: Write-Ahead Logging for concurrent access
- **Connection Pooling**: Thread-safe with configurable limits
- **Optimized Settings**: Large cache, memory temp storage
- **Lazy Loading**: Semantic models loaded only when needed

---

## Development Workflows

### Adding a New MCP Tool

1. **Define the Pydantic model** in `core/models.py`:

```python
class NewToolRequest(BaseModel):
    param: str = Field(..., description="Parameter description")
```

2. **Create the endpoint** in appropriate router:

```python
@router.post("/marm_new_tool", operation_id="marm_new_tool")
async def marm_new_tool(request: NewToolRequest):
    """Tool description with emoji"""
    # Implementation
    return {"status": "success", "message": "Tool executed"}
```

3. **Add WebSocket handler** in `endpoints/websocket_handlers_complete.py`

4. **Write tests** in `tests/` directory

5. **Update documentation** in README and MCP-HANDBOOK

### Modifying Memory System

1. **Backup current database**: `cp data/marm_memory.db data/backup.db`
2. **Update schema** in `core/memory.py` `init_database()` method
3. **Test migration logic** with existing data
4. **Update related endpoints** and models
5. **Run full test suite**

### Performance Optimization

1. **Profile with** `psutil` memory monitoring
2. **Optimize database queries** with EXPLAIN QUERY PLAN
3. **Review connection pool** settings
4. **Test under load** with rate limiting
5. **Monitor Docker metrics** for production deployment

---

## Coding Standards & Patterns

### Python Code Style

- **Follow PEP 8** with 88-character line length (Black formatter)
- **Type hints required** for all function signatures
- **Docstrings** for all public functions (Google style)
- **Structured logging** with `structlog` for all output

### FastAPI Patterns

```python
# Standard endpoint pattern
@router.post("/endpoint_name", operation_id="endpoint_name")
async def endpoint_name(request: RequestModel, http_request: Request):
    """
    Clear description

    Detailed explanation of functionality.
    """
    try:
        # Track usage for analytics
        track_endpoint_usage("endpoint_name", http_request)

        # Business logic
        result = await some_operation()

        # Emit events for automation
        await events.emit('event_name', {'data': result})

        return {
            "status": "success",
            "message": "Clear success message",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Operation failed: {str(e)}")
```

### Error Handling Patterns

1. **Graceful degradation** - Don't break core functionality
2. **Structured error responses** with clear messages
3. **Analytics failures** should never break MCP operations
4. **Database errors** should be caught and logged properly
5. **Semantic search fallback** to text search on failure

### Security Patterns

```python
# XSS protection
from core.memory import sanitize_content
sanitized_content = sanitize_content(user_input)

# Rate limiting (automatic via middleware)
# IP-based with different tiers for different operations

# Input validation (automatic via Pydantic)
class RequestModel(BaseModel):
    content: str = Field(..., max_length=10000)
```

### Database Patterns

```python
# Always use connection pool context manager
with memory.get_connection() as conn:
    # Database operations
    conn.execute("INSERT ...", params)
    # Automatic commit/rollback on context exit
```

---

## Common Development Tasks

### Testing Endpoints

```bash
# Test smart recall
curl -X POST http://localhost:8001/marm_smart_recall \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "session_name": "main"}'

# Test session activation
curl -X POST http://localhost:8001/marm_start \
  -H "Content-Type: application/json" \
  -d '{"session_name": "test_session"}'

# Check system health
curl http://localhost:8001/health
```

### Database Operations

```bash
# Connect to database
# Linux/macOS
sqlite3 ~/.marm/marm_memory.db

# Windows (PowerShell)
sqlite3 "$env:USERPROFILE\.marm\marm_memory.db"

# Common queries
.tables
.schema memories
SELECT * FROM sessions;
SELECT COUNT(*) FROM memories;
```

### Debugging Memory Issues

```python
# Enable debug logging
import structlog
logger = structlog.get_logger()
logger.info("Debug message", key="value")

# Memory usage monitoring
from core.memory import memory
with memory.get_connection() as conn:
    # Database operations with automatic cleanup
```

**Next: Read CODER-WORKFLOWS.md for deployment and collaboration workflows**
