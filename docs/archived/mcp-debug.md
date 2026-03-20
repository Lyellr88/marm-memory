# MCP Connection Debugging Guide

## Problem

- Claude connects fine via `claude mcp add`
- Qwen/Gemini not connecting via settings.json
- Started after WebSocket implementation or outdated pip packages

## Diagnostic Tests

### 1. Basic Server Health

```bash
curl http://localhost:8001/health
curl http://localhost:8001/ready
curl http://localhost:8001/mcp
```

### 2. MCP Protocol Test

```bash
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}}'
```

### 3. WebSocket Test (if this breaks, WebSocket is the culprit)

```bash
python tests/test_websocket.py
```

### 4. Check Server Logs

```bash
docker logs marm-mcp-server --tail 50
```

### 5. Package Version Check

```bash
pip list | grep -E "(fastapi|uvicorn|pydantic)"
```

### 6. Settings.json Validation

Check if settings.json format changed:

- Look for extra commas, brackets
- Verify server URL is exactly: `http://localhost:8001/mcp`
- Check if OAuth/auth fields were accidentally added

## Most Likely Culprits

1. **WebSocket changes broke HTTP MCP endpoint**
2. **Outdated pip packages causing compatibility issues**
3. **Settings.json format corruption**
4. **Server not fully restarting after changes**

## Quick Fixes to Try

1. Restart server completely: `docker restart marm-mcp-server`
2. Test basic MCP endpoint: `curl http://localhost:8001/mcp`
3. Check if WebSocket test passes
4. Update pip packages if versions are old
