# MARM MCP Server Connection Guide for Qwen

This guide explains how to connect Qwen to the MARM MCP Server.

## Prerequisites

1. MARM MCP Server must be running on `http://localhost:8001`
2. Qwen must have access to the settings.json file

## Server Setup

### 1. Start the MCP Server

```bash
cd /mnt/c/Users/lyell/Desktop/gemini-api-test/MARM-Systems-MARM-main/marm-mcp-server
python3 server.py
```

The server will start on port 8001.

### 2. Verify Server is Running

```bash
curl http://localhost:8001
```

You should see server information in JSON format.

## Qwen Configuration

### Settings File

Create a `settings.json` file in your Qwen configuration directory with the following content:

```json
{
  "mcpServers": {
    "marm-memory": {
      "httpUrl": "http://localhost:8001/mcp",
      "authentication": {
        "type": "oauth",
        "clientId": "local_client_b6f3a01e",
        "clientSecret": "local_secret_ad6703cd2b4243ab",
        "authorizationUrl": "http://localhost:8001/oauth/authorize",
        "tokenUrl": "http://localhost:8001/oauth/token",
        "scopes": ["read", "write"]
      }
    }
  },
  "selectedAuthType": "qwen-oauth"
}
```

### Alternative: Mock Authentication

For testing purposes, you can use mock authentication:

```json
{
  "mcpServers": {
    "marm-memory": {
      "httpUrl": "http://localhost:8001/mcp",
      "authentication": {
        "type": "mock"
      }
    }
  },
  "selectedAuthType": "qwen-oauth"
}
```

## Testing the Connection

### 1. Test Server Availability

```bash
curl http://localhost:8001
```

### 2. Test MCP Endpoint

```bash
curl -H "Accept: text/event-stream" http://localhost:8001/mcp
```

### 3. Test OAuth Registration

```bash
curl -X POST http://localhost:8001/oauth/register \
  -H "Content-Type: application/json" \
  -d '{"client_name": "Qwen Client", "redirect_uris": ["http://localhost:8000/callback"]}'
```

## Troubleshooting

### Common Issues

1. **Server not running**: Make sure the MCP server is started on port 8001
2. **Network issues**: Check firewall settings and network connectivity
3. **Authentication errors**: Verify client credentials in settings.json
4. **Port conflicts**: Ensure port 8001 is not used by another application

### WSL2 Network Bottleneck

If you're experiencing slow downloads in WSL2:

1. Create a `.wslconfig` file in your Windows user directory (`C:\\Users\\{username}\\.wslconfig`):

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
firewall=true
autoProxy=true
```

2. Restart WSL2:
```powershell
wsl --shutdown
```

3. Restart your WSL2 distribution

## Available MCP Endpoints

- `GET /` - Server information
- `POST /marm_start` - Start MARM session
- `POST /marm_log_entry` - Log an entry
- `POST /marm_smart_recall` - Recall similar memories
- `POST /marm_notebook_add` - Add notebook entry
- `POST /marm_notebook_use` - Use notebook entry
- `GET /marm_notebook_show` - Show notebook entries
- `/oauth/*` - OAuth authentication endpoints

## Next Steps

1. Configure Qwen to use the settings.json file
2. Test MCP tool integration
3. Begin using MARM memory features in your Qwen workflows