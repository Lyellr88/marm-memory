# MARM MCP Server

Memory Accurate Response Mode (MARM) as an MCP (Model Context Protocol) server for Claude Desktop and other MCP-compatible clients.

## Features

🧠 **Session Management**
- Create and manage multiple named sessions
- Persistent memory across conversations
- Session context tracking and summaries

📚 **User Knowledge Notebook** 
- Store up to 30 key information entries per session
- Activate entries as active instructions
- Persistent storage across sessions

📝 **Structured Logging**
- Add timestamped log entries to sessions
- Track decisions, milestones, and context
- Generate session summaries for context transfer

🔄 **Protocol Management**
- Activate/deactivate MARM protocol
- Session switching and context preservation
- Cross-session knowledge sharing

## Installation

### Prerequisites
- Python 3.8+
- FastMCP library

### Setup
1. Install dependencies:
```bash
cd /home/contact/MARM-Systems/mcp-server
pip install -r requirements.txt
```

2. Test the server:
```bash
python server.py --debug
```

3. Configure Claude Desktop by adding this to your `claude_desktop_config.json`:
```json
{
  "mcp": {
    "servers": {
      "marm-memory": {
        "command": "python",
        "args": ["/home/contact/MARM-Systems/mcp-server/server.py"],
        "env": {
          "PYTHONPATH": "/home/contact/MARM-Systems/mcp-server"
        }
      }
    }
  }
}
```

## MCP Tools Available

### Core Session Management
- **`marm_start`** - Activate MARM protocol for a session
- **`marm_show_context`** - View current session status and context  
- **`marm_list_sessions`** - List all available sessions

### Logging & Memory
- **`marm_log_entry`** - Add structured log entries to sessions
- **`marm_session_summary`** - Generate session summaries for context transfer

### Knowledge Notebook
- **`marm_notebook_add`** - Store key information in your notebook
- **`marm_notebook_show`** - Display all notebook entries
- **`marm_notebook_use`** - Activate notebook entries as instructions

## Usage Examples

### Start a new session
```
Use marm_start with session_name="project-alpha" to begin memory tracking.
```

### Add knowledge to notebook
```
Use marm_notebook_add with name="api_style" and data="Always use REST conventions with proper HTTP status codes"
```

### Log important decisions
```
Use marm_log_entry with entry="[2025-01-15-Authentication-Decided to use JWT tokens]"
```

### Generate session summary
```
Use marm_session_summary to create a transferable context summary.
```

## Data Storage

All MARM data is stored locally in:
- `~/.marm-mcp/sessions.json` - Session data and logs
- `~/.marm-mcp/notebooks.json` - Knowledge notebook entries  
- `~/.marm-mcp/config.json` - Current session and protocol state

## Architecture

The MCP server provides a bridge between Claude Desktop and MARM's core functionality:

```
Claude Desktop → MCP Protocol → MARM Server → Local Storage
```

Each MCP tool corresponds to a core MARM command, maintaining the same functionality while integrating seamlessly with Claude Desktop's interface.

## Differences from Web Version

- **Storage**: Uses local file system instead of browser localStorage
- **Interface**: MCP tools instead of chat commands
- **Context**: Integrated directly into Claude Desktop conversations
- **Persistence**: Data persists across different Claude Desktop sessions

## Troubleshooting

### Server won't start
- Check Python version: `python --version` (need 3.8+)
- Install FastMCP: `pip install fastmcp>=0.4.0`
- Check file permissions on server.py

### Claude Desktop not connecting
- Verify config file location and format
- Check server.py path in configuration
- Restart Claude Desktop after config changes

### Tools not appearing
- Confirm server is running: `python server.py --debug`
- Check Claude Desktop logs for MCP connection errors
- Verify all dependencies are installed

## License

MIT License - Same as main MARM project