---
name: update-docs
description: Core documentation sync enforcer for MARM-Systems. Audits only README, MCP-HANDBOOK, CONTRIBUTING, and FAQ against live MARM MCP behavior, then applies surgical updates.
metadata:
  project: MARM-Systems
  docs_dir: docs/
  package_dir: marm-mcp-server/marm-docs/
  notes: "Core-docs-only scope. Use update-sub-docs for install/support docs."
---

# MARM Core Docs Sync Enforcer

You are a documentation auditor for MARM-Systems. When invoked, compare live MCP server behavior against active docs and keep documentation aligned without rewriting stable sections.

## Your Task

1. Read source-of-truth implementation files in `marm-mcp-server/`.
2. Read core documentation surfaces only.
3. Compare and flag discrepancies.
4. Apply only targeted edits when requested.

---

## Step 1: Read Source Truth

Always read these first:

- `marm-mcp-server/marm_mcp_server/server.py`
- `marm-mcp-server/marm_mcp_server/server_stdio.py`
- `marm-mcp-server/marm_mcp_server/config/settings.py`
- `marm-mcp-server/marm_mcp_server/core/models.py`
- `marm-mcp-server/marm_mcp_server/core/rate_limiter.py`
- `marm-mcp-server/marm_mcp_server/middleware/rate_limiting.py`
- `marm-mcp-server/marm_mcp_server/endpoints/` (relevant modules only)
- `marm-mcp-server/server.json`
- `marm-mcp-server/pyproject.toml`
- `marm-mcp-server/Dockerfile`

Extract and track:

- Current server version and package version
- Active tool surface (HTTP + STDIO names/shape)
- CLI flags (`python -m marm_mcp_server ...`)
- Transport modes (HTTP vs STDIO)
- Auth behavior (when `MARM_API_KEY` is required)
- Rate limit behavior (actual wired behavior, not just constants)
- Any automation behavior (startup docs load, refresh, queue behavior)

---

## Step 2: Read Documentation

Read only these docs by default:

- `README.md`
- `MCP-HANDBOOK.md`
- `CONTRIBUTING.md`
- `docs/FAQ.md`

Packaged mirrors (only when relevant to the specific edit):

- `marm-mcp-server/marm-docs/README.md`
- `marm-mcp-server/marm-docs/MCP-HANDBOOK.md`

Ignore unless user explicitly asks:

- `CHANGELOG.md`
- `docs/ACKNOWLEDGMENTS.md`
- `docs/PROTOCOL.md`
- `docs/INSTALL-WINDOWS.md`
- `docs/INSTALL-LINUX.md`
- `docs/INSTALL-DOCKER.md`
- `docs/INSTALL-PLATFORMS.md`
- `marm-mcp-server/marm-docs/PROTOCOL.md`
- `marm-mcp-server/marm-docs/QUICK-INSTALL.md`
- `docs/archived/**`
- `docs/future/**`
- `dump.md`, `dump2.md`
- Temporary test artifacts or generated logs

---

## Step 3: Audit Checks

For each doc, classify and report checks as `OK`, `OUTDATED`, or `MISSING`.

### Universal Checks (apply to every doc)

| Check | What to verify |
|-------|---------------|
| Tool references | MCP tools named in docs exist and match current names/signatures |
| CLI commands | Example commands match current flags and entrypoints |
| Version mentions | If versions are explicit, they align with current source/package |
| File paths | Any paths referenced exist and are correct |
| Feature behavior | Docs match actual behavior (auth, startup, refresh, rate limiting, transport) |

### By Doc Purpose

User-facing docs (`README`, `FAQ` sections that are user-facing):
- Transport commands accurate for Claude/Codex/Gemini/Qwen/VS Code/Cursor where documented
- HTTP vs STDIO distinctions are correct
- Docker guidance matches actual Dockerfile behavior
- Auth/key guidance reflects real server behavior

Core behavior docs (`MCP-HANDBOOK`, `FAQ`, `README` architecture/tooling sections):
- Protocol/tool workflow matches current architecture (no stale removed tools)
- Session/startup behavior is current
- Health/status and operational commands are accurate
- Tool-count claims match current exposed surface

Contributor docs (`CONTRIBUTING`):
- Setup commands and paths are current
- Workflow instructions match actual repo CI/release process
- Branch/PR instructions are consistent with current policy

### Cross-Doc Consistency

| Check | What to verify |
|-------|---------------|
| Terminology | Same terms used across all docs — flag any mismatches |
| Transport language | HTTP/STDIO wording is consistent across root docs and packaged mirrors |
| Tool naming | Consolidated/renamed tool names are consistent everywhere |
| Path references | Same folder structure described everywhere |

---

## Step 4: Generate Report

```
=== DOCUMENTATION SYNC REPORT ===
Generated: [date]

[doc-file]
  Function references ......... OK / OUTDATED (missing: FuncA, stale: FuncB)
  Parameter references ........ OK / OUTDATED (missing: -ParamX)
  Version number .............. OK / OUTDATED (doc: X.X, actual: X.X)
  Feature list ................ OK / OUTDATED
  [etc.]

[doc-file]
  [etc.]

(repeat for each discovered doc)

Cross-Doc Consistency
  Terminology ................. OK / CONFLICT ([term] differs between [doc-a] and [doc-b])
  Version references .......... OK / CONFLICT
  [etc.]

---
SUMMARY
  Outdated: [count]
  Missing: [count]
  OK: [count]

Would you like me to apply these updates? (yes/no/specific items)
```

---

## Step 5: Apply Updates (if requested)

If the user says yes (or specifies items):

1. Apply surgical edits only to requested docs.
2. Keep current doc voice and section structure.
3. Update packaged mirrors only for touched core docs (`README`, `MCP-HANDBOOK`) when needed.
4. Do not update `CHANGELOG.md` unless user explicitly asks.
5. Summarize per-file changes with exact file paths.

---

## Important Rules

- Never rewrite entire docs unless explicitly asked.
- Prefer minimal, high-signal edits.
- Flag ambiguous items before changing them.
- Treat implementation files as truth over older docs.
- Skip archived/historical docs unless requested.
- Do not re-introduce removed features/terms in docs.
- Keep only core mirror pairs aligned:
  - `README.md` <-> `marm-mcp-server/marm-docs/README.md`
  - `MCP-HANDBOOK.md` <-> `marm-mcp-server/marm-docs/MCP-HANDBOOK.md`
