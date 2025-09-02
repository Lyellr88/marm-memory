# Enhanced OAuth 2.1 MCP Wrapper for MARM Systems

🔒 **Production-ready OAuth 2.1 enhanced wrapper that solves Claude Code authentication issues**

## Architecture
```
Claude Code → Enhanced OAuth 2.1 Wrapper → MARM MCP Server  
```

## Problem Solved
- ❌ OAuth tokens expire without refresh capability
- ❌ Repeated authentication requirements  
- ❌ Unstable MCP connections
- ❌ Session authentication failures

## Enhanced OAuth 2.1 Features
- ✅ **Automatic Token Refresh** with PKCE security (S256)
- ✅ **Persistent Authentication** across Claude Code sessions
- ✅ **Dynamic Client Registration** (DCR) support
- ✅ **Enhanced Error Handling** with graceful retry logic
- ✅ **Session Isolation** and management
- ✅ **Production-Ready** security implementation

## MARM Protocol Support
Full compatibility with all MARM tools:
- `marm_start` - Session activation with OAuth enhancement
- `marm_log_entry` - Structured logging via OAuth proxy
- `marm_notebook_add` - Knowledge storage with persistent auth
- `marm_session_summary` - Context summarization
- `marm_show_context` - Session status display
- `oauth_status` - OAuth authentication details
- `deployment_status` - FastMCP cloud readiness

## FastMCP Cloud Deployment

### Files Required
- ✅ `server.py` - Main Enhanced OAuth MCP server
- ✅ `requirements.txt` - Minimal dependencies (fastmcp + httpx)
- ✅ `README.md` - This documentation
- ✅ `.env` - Configuration (optional)

### Configuration
Set environment variable:
```bash
MARM_SERVER_URL=https://marm-systems.fastmcp.app/mcp
```

### Deployment Command
```bash
# Deploy to fastmcp.cloud
fastmcp deploy enhanced-oauth-marm-wrapper
```

## Local Testing
```bash
# Install dependencies
pip install -r requirements.txt

# Run HTTP server
python3 server.py --http --port 9000

# Test with curl
curl -X POST http://localhost:9000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

## Benefits
- **Seamless Authentication**: No more repeated OAuth flows
- **Enhanced Reliability**: Automatic token refresh prevents connection failures
- **Production Security**: Professional-grade OAuth 2.1 implementation
- **Easy Deployment**: Single-step deployment to fastmcp.cloud
- **Full MARM Support**: All original MARM features preserved and enhanced

## Version History
- **v2.0.2**: Production-ready OAuth 2.1 wrapper with enhanced features
- **v1.0.0**: Initial OAuth wrapper implementation

---

*This wrapper provides the 3-layer architecture requested: Enhanced OAuth 2.1 Client → FastMCP Wrapper → MARM MCP Server, solving persistent authentication issues with Claude Code.*