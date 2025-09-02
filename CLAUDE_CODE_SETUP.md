# MARM MCP Server for Claude Code Setup

This guide explains how to set up and use the MARM MCP Server with Claude Code for enhanced session management and persistent memory.

## Quick Setup

### 1. Install the MCP Server

```bash
cd /home/contact/MARM-Systems/mcp-server
./install.sh
```

### 1.5. Service Setup (Automatic Startup)

The MARM MCP server is configured to run automatically as a system service. It should already be running on port 9999.

Check service status:
```bash
sudo systemctl status marm-mcp-server.service
```

Service commands:
```bash
# Start the service
sudo systemctl start marm-mcp-server.service

# Stop the service  
sudo systemctl stop marm-mcp-server.service

# Restart the service
sudo systemctl restart marm-mcp-server.service

# View logs
sudo journalctl -u marm-mcp-server.service -f
```

### 2. Configure Claude Code

You have three options to configure the MCP server:

#### Option A: HTTP Transport (Recommended - Uses Running Service)

Since the MCP server is running as a service on port 9999, simply connect Claude Code:

```bash
claude mcp add --transport http marm-memory http://localhost:9999
```

**Benefits of HTTP transport:**
- Uses the automatically-started system service
- Supports multiple concurrent Claude Code instances
- Server runs independently and survives reboots
- Better for development and testing
- Can be accessed from other machines on network

**Note:** The service automatically starts the server in HTTP mode, so no manual server startup is needed.

#### Option B: Using Claude MCP Add Command (STDIO)

```bash
claude mcp add marm-memory --env PYTHONPATH=/home/contact/MARM-Systems/mcp-server -- python3 /home/contact/MARM-Systems/mcp-server/server.py
```

This command will:
- Add the MARM memory server to Claude Code
- Set the required environment variables
- Configure the Python command and script path

#### Option C: Manual Configuration

If the CLI command doesn't work, you can manually add this configuration to your Claude Code MCP settings:

**For Linux/macOS:**
```json
{
  "mcp": {
    "servers": {
      "marm-memory": {
        "command": "python3",
        "args": ["/home/contact/MARM-Systems/mcp-server/server.py"],
        "env": {
          "PYTHONPATH": "/home/contact/MARM-Systems/mcp-server"
        }
      }
    }
  }
}
```

### 3. Verify Installation

Check that the server is configured correctly:
```bash
claude mcp list
```

You should see "marm-memory" in the list of configured servers.

### 4. Restart Claude Code

After adding the configuration, restart Claude Code to load the MCP server.

## Available Tools

Once configured, you'll have access to these MCP tools in Claude Code:

### 🚀 Session Management
- **`marm_start`** - Activate MARM protocol for a session
- **`marm_show_context`** - View current session status and context
- **`marm_list_sessions`** - List all available sessions

### 📝 Memory & Logging
- **`marm_log_entry`** - Add structured log entries to sessions
- **`marm_session_summary`** - Generate session summaries for context transfer

### 📚 Knowledge Notebook
- **`marm_notebook_add`** - Store key information in your notebook
- **`marm_notebook_show`** - Display all notebook entries
- **`marm_notebook_use`** - Activate notebook entries as instructions

## Usage Examples

### Starting Your First Session

```
Use marm_start with session_name="coding-project" to begin tracking your work session.
```

This will:
- Create a new session called "coding-project"
- Activate the MARM protocol
- Enable persistent memory across conversations

### Adding Knowledge to Your Notebook

```
Use marm_notebook_add with:
- name="coding_standards" 
- data="Use TypeScript strict mode, ESLint configuration, and Jest for testing"
```

This stores coding standards that can be referenced across sessions.

### Logging Important Decisions

```
Use marm_log_entry with entry="[2025-01-15-Architecture-Decided to use microservices pattern for scalability]"
```

This creates a timestamped log entry for future reference.

### Activating Knowledge for Current Work

```
Use marm_notebook_use with names="coding_standards,api_conventions" to activate stored knowledge.
```

This makes your stored knowledge active for the current session.

### Viewing Session Context

```
Use marm_show_context to see:
- Current session status
- Recent log entries
- Active notebook entries
- Protocol status
```

### Generating Session Summaries

```
Use marm_session_summary to create a formatted summary of your session for transferring context to new conversations.
```

## Advanced Workflows

### 1. Project Setup Workflow
```
1. marm_start session_name="new-project"
2. marm_notebook_add name="project_requirements" data="Build REST API with authentication"
3. marm_notebook_add name="tech_stack" data="Node.js, Express, PostgreSQL, JWT"
4. marm_notebook_use names="project_requirements,tech_stack"
5. Begin coding with Claude Code
```

### 2. Code Review Workflow
```
1. marm_log_entry entry="[2025-01-15-Review-Starting code review of authentication module]"
2. Review code with Claude Code
3. marm_log_entry entry="[2025-01-15-Review-Found security issue in JWT validation]"
4. Fix issues
5. marm_log_entry entry="[2025-01-15-Review-Security issues resolved, tests passing]"
```

### 3. Context Transfer Workflow
```
1. marm_session_summary (copy output)
2. Start new Claude Code session
3. Paste summary as context
4. marm_start session_name="same-project-continued"
5. Continue work with full context
```

## Data Storage

All MARM data is stored locally in:
- `~/.marm-mcp/sessions.json` - Session data and logs
- `~/.marm-mcp/notebooks.json` - Knowledge notebook entries
- `~/.marm-mcp/config.json` - Current session and protocol state

## Benefits for Claude Code Users

### 🧠 **Persistent Memory**
- Your conversations and decisions are remembered across sessions
- Context doesn't get lost when starting new Claude Code instances

### 📋 **Structured Organization**
- Log important decisions with timestamps
- Store reusable knowledge in your notebook
- Track project progress systematically

### 🔄 **Session Continuity**
- Generate summaries to transfer context between sessions
- Switch between different projects seamlessly
- Maintain context across long development cycles

### 📚 **Knowledge Management**
- Build a personal knowledge base of coding standards
- Store project-specific requirements and decisions
- Activate relevant knowledge for current work

## Troubleshooting

### Server Won't Start
```bash
# Check Python version
python3 --version

# Test server manually
python3 /home/contact/MARM-Systems/mcp-server/server.py --debug

# Check dependencies
pip3 install -r /home/contact/MARM-Systems/mcp-server/requirements.txt
```

### Tools Not Appearing in Claude Code
1. Verify MCP configuration is correct
2. Restart Claude Code completely
3. Check server is running: `ps aux | grep server.py`
4. Review Claude Code logs for MCP connection errors

### Data Not Persisting
- Check permissions on `~/.marm-mcp/` directory
- Verify JSON files are not corrupted
- Use `marm_show_context` to confirm session is active

## Best Practices

### 1. Session Naming
- Use descriptive names: "web-redesign", "api-refactor", "bug-fixes"
- Keep names short but meaningful
- Use consistent naming conventions

### 2. Log Entries
- Use structured format: `[YYYY-MM-DD-Topic-Summary]`
- Log decisions, not just actions
- Include context for future reference

### 3. Notebook Management
- Keep entries focused and actionable
- Use clear, descriptive names
- Regular cleanup of outdated entries

### 4. Context Transfer
- Generate summaries before long breaks
- Include relevant background in summaries
- Test context transfer with simple questions

## Integration Tips

### With Git Workflows
```
1. marm_start session_name="feature-auth"
2. marm_log_entry entry="[2025-01-15-Git-Starting feature/authentication branch]"
3. Work on feature
4. marm_log_entry entry="[2025-01-15-Git-Feature complete, ready for PR]"
5. marm_session_summary (include in PR description)
```

### With Testing
```
1. marm_notebook_add name="test_standards" data="All functions need unit tests, 80% coverage minimum"
2. marm_notebook_use names="test_standards"
3. Write code and tests with standards active
4. marm_log_entry entry="[2025-01-15-Testing-All tests passing, 85% coverage achieved]"
```

---

**Need Help?** Check the main README.md or run the installation script with debug mode:
```bash
python3 server.py --debug
```