# MCP Client Command Generator Plan

## Goal

Create an interactive script that prints canonical MARM MCP connection commands/configs for each supported client and transport.

This is a command generator, not a live validator. It should save time when updating docs or helping users connect MARM.

## Proposed Script

`scripts/mcp-client-commands.py`

## Interactive Flow

```text
MARM MCP Client Command Generator

Choose deployment mode:
1. Local pip HTTP
2. Local pip STDIO
3. Docker HTTP with key
4. Docker STDIO

Choose client:
1. Claude Code
2. Codex
3. Gemini CLI
4. Qwen Code
5. VS Code
6. Cursor
7. All
```

## Output Example

```text
Codex - Docker HTTP with key

PowerShell:
$env:MARM_API_KEY = "your-generated-key"
codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY

TOML:
[mcp_servers.marm-memory]
url = "http://localhost:8001/mcp"
enabled = true
bearer_token_env_var = "MARM_API_KEY"
```

## Source of Truth Rules

- Pull current package/module command names from live repo files:
  - `marm-mcp-server/pyproject.toml`
  - `marm-mcp-server/Dockerfile`
  - `.vscode/mcp.json` if present
  - `.cursor/mcp.json` if present
- Do not invent client syntax.
- Keep client syntax hardcoded only after it has been verified against official docs or live local testing.
- Include a warning banner if a client command has not been recently verified.

## Supported Outputs

- Claude Code CLI command
- Codex CLI command and TOML
- Gemini CLI command and JSON
- Qwen CLI command and JSON
- VS Code `.vscode/mcp.json`
- Cursor `.cursor/mcp.json`
- Docker direct HTTP and STDIO examples

## Non-Goals

- Do not connect MCP automatically.
- Do not verify installed clients.
- Do not browse official docs.
- Do not write config files by default.

## Future Nice-to-Haves

- Copy selected output to clipboard.
- Print Windows/macOS/Linux volume mount variants.
- Add a `verified_on` date per client.
- Add JSON schema validation for generated VS Code/Cursor snippets.
