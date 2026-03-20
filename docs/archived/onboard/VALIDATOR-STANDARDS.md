# VALIDATOR STANDARDS
## Quality Metrics, Architectural Validation & Best Practices

---

## PRODUCTION-READY QUALITY STANDARDS

### PERFORMANCE BENCHMARKS

**Response Time Requirements:**
```
MCP Tool Execution:
- Standard operations: <100ms (marm_log_entry, marm_notebook_add)
- Memory operations: <200ms (marm_contextual_log with embedding)
- Search operations: <500ms (marm_smart_recall with semantic search)
- System operations: <50ms (marm_system_info, marm_current_context)

WebSocket Communication:
- Connection handshake: <100ms
- Message processing: <50ms additional overhead vs HTTP
- Rate limiting response: <25ms

Database Performance:
- SQLite query execution: <50ms for standard operations
- Connection acquisition: <10ms from pool
- Transaction commit: <25ms with WAL mode
```

**Resource Utilization Limits:**
```
Memory Usage:
- Base server footprint: <100MB
- With AI model loaded: <500MB
- Per active session: <10MB additional
- Memory growth rate: Linear with data, not exponential

CPU Usage:
- Idle state: <5% CPU utilization
- Under normal load: <25% CPU utilization
- Peak load (rate limit): <50% CPU utilization
- AI model inference: Burst to 80%, settling to <30%
```

**Scalability Requirements:**
```
Concurrent Connections:
- HTTP MCP clients: 10 simultaneous without degradation
- WebSocket connections: 5 simultaneous with full functionality
- Database connections: Pool of 5 with proper queuing

Data Volume Handling:
- Memory storage: 10,000+ memories without significant slowdown
- Session management: 100+ active sessions supported
- Search operations: Sub-second response with 1,000+ stored memories
```

### RELIABILITY STANDARDS

**Uptime and Availability:**
- **99.9% uptime** during normal operation (excluding planned maintenance)
- **Graceful degradation** when AI features unavailable
- **Fast recovery** from transient failures (<30 seconds)
- **Data consistency** maintained during unexpected shutdowns

**Error Handling Requirements:**
```python
# Error categories and handling standards:

1. Transient Errors (Network, temporary resource unavailability)
   - Automatic retry with exponential backoff
   - Client notification of retry attempts
   - Graceful fallback to cached results when appropriate

2. Resource Errors (Memory exhaustion, disk space)
   - Immediate error response to client
   - System health monitoring alerts
   - Automatic cleanup and recovery procedures

3. Data Errors (Corrupted database, invalid input)
   - Detailed error logging for debugging
   - Safe error responses (no sensitive data exposure)
   - Data integrity protection (rollback on failure)

4. System Errors (Programming bugs, configuration issues)
   - Comprehensive error logging with stack traces
   - Fail-safe default behaviors
   - Clear error messages for user troubleshooting
```

---

## SECURITY COMPLIANCE STANDARDS

### INPUT VALIDATION REQUIREMENTS

**MCP Parameter Validation:**
```python
# Standard validation patterns for all MCP tools:

String Parameters:
- Maximum length: 10,000 characters for content, 100 for names
- Character encoding: UTF-8 validation required
- HTML/Script sanitization: Remove/escape potentially dangerous content
- SQL injection prevention: Parameterized queries only

Numeric Parameters:
- Range validation: Positive integers where applicable
- Type validation: Reject non-numeric input for numeric fields
- Overflow protection: Maximum values defined and enforced

JSON Data:
- Schema validation: Required fields present and correctly typed
- Size limits: Maximum 1MB JSON payload per request
- Depth limits: Maximum 10 levels of nested objects/arrays
```

**Database Security Standards:**
```sql
-- Required security patterns:

1. Parameterized Queries Only
   ✅ cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
   ❌ cursor.execute(f"SELECT * FROM memories WHERE id = {memory_id}")

2. Input Sanitization Before Storage
   ✅ content = html.escape(user_input)
   ❌ Direct storage of user input without validation

3. Error Message Security
   ✅ "Database operation failed"
   ❌ "SQL error: table 'secret_table' doesn't exist"
```

### AUTHENTICATION & AUTHORIZATION

**Current Security Model Validation:**
```
Network-Level Security:
- Server binding: localhost/127.0.0.1 only (verified)
- Port exposure: 8001 only for MCP communication
- CORS configuration: Restrictive cross-origin policies
- TLS/SSL: Optional for localhost deployment

Rate Limiting Security:
- IP-based tracking: Prevents single-source abuse
- Tiered limiting: Different limits for different operation types
- Bypass resistance: Multiple validation layers
- Graceful degradation: Service remains available under attack
```

**Future Authentication Readiness:**
```python
# Architecture prepared for future authentication:
- Session management framework exists
- User context tracking available
- Rate limiting by user ID (not just IP) possible
- Role-based access control foundations in place
```

### DATA PROTECTION STANDARDS

**Sensitive Data Classification:**
```
PUBLIC: System status, capabilities, documentation
INTERNAL: Usage analytics (anonymized), performance metrics
CONFIDENTIAL: User conversations, session data, notebook entries
RESTRICTED: Raw usage logs with IP addresses, debug information
```

**Data Handling Requirements:**
```
Storage Security:
- SQLite database file permissions: 600 (owner read/write only)
- Backup encryption: Required for production environments
- Log rotation: Automatic cleanup of sensitive debug logs
- Memory protection: Sensitive data cleared from RAM after use

Data Export/Import:
- Sanitization: Remove or anonymize sensitive data
- Validation: Verify data integrity during transfer
- Access control: Restricted to authorized users only
- Audit logging: Track all data export/import operations
```

---

## ARCHITECTURAL COMPLIANCE STANDARDS

### MCP PROTOCOL COMPLIANCE

**JSON-RPC 2.0 Requirements:**
```json
// Standard request format validation:
{
  "jsonrpc": "2.0",          // Required: Exact version string
  "method": "tools/call",    // Required: Valid MCP method
  "params": { ... },         // Required: Method-specific parameters
  "id": "unique-id"          // Required: Request tracking ID
}

// Standard response format validation:
{
  "jsonrpc": "2.0",          // Required: Exact version string
  "result": { ... },         // Success: Tool execution results
  "id": "unique-id"          // Required: Matching request ID
}

// Error response format validation:
{
  "jsonrpc": "2.0",          // Required: Exact version string
  "error": {                 // Error case
    "code": -32600,          // Required: Standard error code
    "message": "Invalid Request", // Required: Human-readable message
    "data": { ... }          // Optional: Additional error context
  },
  "id": "unique-id"          // Required: Matching request ID
}
```

**MCP Tool Implementation Standards:**
```python
# Required patterns for all MCP tools:

1. Parameter Validation
   - Type checking for all input parameters
   - Required parameter presence validation
   - Range/format validation for specific parameter types

2. Error Handling
   - Standard MCP error codes used
   - Clear, actionable error messages
   - No sensitive data in error responses

3. Response Formatting
   - Consistent data structure across tools
   - Size limiting (1MB max response)
   - Proper JSON serialization

4. Documentation
   - Tool purpose clearly documented
   - Parameter specifications complete
   - Usage examples provided
```

### WEBSOCKET IMPLEMENTATION STANDARDS

**WebSocket Protocol Compliance:**
```python
# Required WebSocket behaviors:

Connection Management:
- Proper handshake completion
- Heartbeat/ping-pong for connection health
- Graceful connection closure
- Resource cleanup on disconnect

Message Handling:
- JSON-RPC 2.0 compliance over WebSocket
- Message framing according to WebSocket RFC
- Binary message support (if needed for embeddings)
- Error propagation maintains WebSocket connection

Rate Limiting:
- Per-connection rate limiting
- Consistent with HTTP rate limits
- WebSocket-specific abuse prevention
- Fair resource allocation across connections
```

**HTTP/WebSocket Parity Requirements:**
```python
# Functional equivalence validation:

Tool Availability:
✅ All 19 MCP tools accessible via both protocols
✅ Identical parameter handling and validation
✅ Equivalent response formats and data
✅ Same error codes and messages

Performance Characteristics:
✅ WebSocket overhead <50ms additional latency
✅ Memory usage comparable between protocols
✅ Rate limiting consistency maintained
✅ Resource cleanup equivalent
```

### DATABASE ARCHITECTURE STANDARDS

**SQLite Configuration Requirements:**
```sql
-- Required database settings:
PRAGMA journal_mode = WAL;           -- Write-Ahead Logging for concurrency
PRAGMA synchronous = NORMAL;         -- Balance safety and performance
PRAGMA cache_size = -64000;         -- 64MB cache size
PRAGMA temp_store = MEMORY;          -- Temporary tables in memory
PRAGMA mmap_size = 268435456;       -- 256MB memory mapping
```

**Schema Design Standards:**
```sql
-- Required patterns for all tables:

Primary Keys:
- TEXT PRIMARY KEY for UUID-based IDs
- INTEGER PRIMARY KEY AUTOINCREMENT for sequential IDs
- Compound keys only when necessary for performance

Indexes:
- Index on frequently queried columns
- Compound indexes for multi-column queries
- Avoid over-indexing (impacts write performance)

Data Types:
- TEXT for variable-length strings
- INTEGER for numeric values
- BLOB for binary data (embeddings)
- JSON for structured data (with validation)

Constraints:
- NOT NULL for required fields
- DEFAULT values for optional fields
- CHECK constraints for data validation
- FOREIGN KEY constraints where appropriate
```

**Connection Pool Management:**
```python
# Required connection pool configuration:

Pool Settings:
- Maximum connections: 5 (default for SQLite)
- Connection timeout: 30 seconds
- Pool recycle: 3600 seconds (1 hour)
- Connection validation: Pre-ping enabled

Transaction Management:
- Automatic transaction rollback on error
- Connection return to pool after transaction
- Deadlock detection and retry logic
- Long-running transaction monitoring
```

---

## CODE QUALITY STANDARDS

### PYTHON CODE QUALITY REQUIREMENTS

**Code Style and Structure:**
```python
# Required code patterns:

Error Handling:
try:
    # Operation that might fail
    result = risky_operation()
    return {"success": True, "result": result}
except SpecificException as e:
    logger.error("Operation failed", error=str(e), context={"param": value})
    return {"success": False, "error": "User-friendly error message"}
except Exception as e:
    logger.exception("Unexpected error in operation")
    return {"success": False, "error": "Internal server error"}

Logging Standards:
import structlog
logger = structlog.get_logger()

# Good logging:
logger.info("Memory stored", memory_id=memory_id, session=session_name)
logger.warning("Rate limit approached", ip=client_ip, count=request_count)
logger.error("Database error", operation="memory_store", error=str(e))

# Bad logging:
print(f"Memory {memory_id} stored")  # No structured data
logger.info("Something happened")    # Vague message
```

**Documentation Requirements:**
```python
# Required docstring format:
def marm_smart_recall(query: str, search_all: bool = False) -> dict:
    """
    Perform semantic search across stored memories using AI embeddings.

    Args:
        query: Search query string for similarity matching
        search_all: If True, search all memories; if False, search current session

    Returns:
        dict: {
            "success": bool,
            "memories": list[dict],  # Matching memories with similarity scores
            "total_found": int,
            "search_time_ms": float
        }

    Raises:
        ValueError: If query is empty or invalid
        RuntimeError: If semantic search model is unavailable
    """
```

### TESTING STANDARDS

**Test Coverage Requirements:**
```python
# Required test categories for each MCP tool:

1. Unit Tests (90%+ coverage required)
   - Valid parameter handling
   - Invalid parameter rejection
   - Error condition handling
   - Response format validation

2. Integration Tests
   - Database interaction correctness
   - AI model integration functionality
   - Rate limiting integration
   - WebSocket protocol compatibility

3. Performance Tests
   - Response time benchmarks
   - Memory usage monitoring
   - Concurrent request handling
   - Resource cleanup verification

4. Security Tests
   - Input validation effectiveness
   - SQL injection prevention
   - XSS protection verification
   - Rate limit bypass resistance
```

**Test File Organization:**
```
tests/
├── test_integration.py          # End-to-end system tests
├── test_performance.py          # Performance benchmarks
├── test_security.py             # Security validation tests
├── test_memory_usage.py         # Resource usage tests
├── test_mcp_size_limits.py      # MCP compliance tests
├── test_websocket.py            # WebSocket-specific tests
└── test_docker_*.py             # Docker deployment tests
```

### CONFIGURATION MANAGEMENT STANDARDS

**Environment Configuration:**
```python
# Required configuration patterns:

Settings Validation:
class Settings:
    # Required: Type hints for all settings
    # Required: Default values for optional settings
    # Required: Validation for critical settings

    server_host: str = "127.0.0.1"  # Security: localhost only
    server_port: int = 8001         # Standard: MCP port
    database_path: str = "./data/marm.db"  # Default: relative path
    max_connections: int = 5        # Performance: connection pool size

    def validate(self):
        """Validate configuration before server startup."""
        if self.max_connections < 1:
            raise ValueError("max_connections must be positive")
        # Additional validation logic...
```

**Feature Flags and Optional Dependencies:**
```python
# Required pattern for optional features:

try:
    from sentence_transformers import SentenceTransformer
    SEMANTIC_SEARCH_AVAILABLE = True
except ImportError:
    SEMANTIC_SEARCH_AVAILABLE = False
    logger.warning("Semantic search disabled - install sentence-transformers")

# Feature usage with graceful degradation:
if SEMANTIC_SEARCH_AVAILABLE:
    # Use AI-powered semantic search
    return semantic_search(query)
else:
    # Fall back to text-based search
    return simple_text_search(query)
```

---

## MONITORING & OBSERVABILITY STANDARDS

**Health Check Requirements:**
```python
# Required health check endpoints:

/health - Basic service health
{
    "status": "healthy",
    "timestamp": "2025-01-XX:XX:XX",
    "version": "2.2.5",
    "uptime_seconds": 3600
}

/ready - Service readiness for traffic
{
    "status": "ready",
    "database": "connected",
    "ai_model": "loaded",
    "mcp_tools": 19
}
```

**Metrics Collection Standards:**
```python
# Required metrics tracking:

Performance Metrics:
- Request count per MCP tool
- Response time percentiles (50th, 95th, 99th)
- Error rate by tool and error type
- Database query performance
- Memory usage trends

Business Metrics:
- Active sessions count
- Memory storage rate
- Search query frequency
- WebSocket vs HTTP usage ratio

System Metrics:
- CPU and memory utilization
- Database connection pool usage
- Rate limiting trigger frequency
- AI model inference time
```

These comprehensive standards ensure MARM maintains production-ready quality while enabling systematic validation and continuous improvement.