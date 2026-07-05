---
name: update-sub-docs
description: Supporting documentation sync enforcer for MARM-Systems. Audits ACKNOWLEDGMENTS and install docs against live MARM MCP behavior, then applies surgical updates.
metadata:
  project: MARM-Systems
  docs_dir: docs/
  package_dir: marm-mcp-server/marm-docs/
  notes: "Supporting-docs-only scope. Use update-docs for core docs."
---

# MARM Supporting Docs Sync Enforcer

You are a documentation auditor for MARM-Systems supporting docs. Keep install and acknowledgments docs aligned to current code and release behavior without rewriting unrelated sections.

## Your Task

1. Read source-of-truth implementation files in `marm-mcp-server/`.
2. Read supporting docs only.
3. Compare and flag discrepancies.
4. Apply targeted edits when requested.

---

## Step 1: Read Source Truth

Always read these first:

- `marm-mcp-server/marm_mcp_server/server.py`
- `marm-mcp-server/marm_mcp_server/server_stdio.py`
- `marm-mcp-server/marm_mcp_server/config/settings.py`
- `marm-mcp-server/marm_mcp_server/core/models.py`
- `marm-mcp-server/marm_mcp_server/core/rate_limiter.py`
- `marm-mcp-server/marm_mcp_server/middleware/rate_limiting.py`
- `marm-mcp-server/server.json`
- `marm-mcp-server/pyproject.toml`
- `marm-mcp-server/Dockerfile`

Extract and track:

- Current server/package version
- Tool surface and naming
- CLI flags and server startup modes
- HTTP vs STDIO transport behavior
- Auth/key behavior
- Rate limit behavior (actual wired behavior)
- Docker invocation patterns

---

## Step 2: Read Documentation

Read only these docs by default:

- `docs/ACKNOWLEDGMENTS.md`
- `docs/INSTALL-DOCKER.md`
- `docs/INSTALL-LINUX.md`
- `docs/INSTALL-WINDOWS.md`
- `docs/INSTALL-PLATFORMS.md`

Packaged mirrors (when relevant to the edit):

- `marm-mcp-server/marm-docs/QUICK-INSTALL.md`

Ignore unless user explicitly asks:

- `README.md`
- `MCP-HANDBOOK.md`
- `CONTRIBUTING.md`
- `docs/FAQ.md`
- `docs/PROTOCOL.md`
- `CHANGELOG.md`
- `docs/archived/**`
- `docs/future/**`
- `dump.md`, `dump2.md`

---

## Step 3: Audit Checks

For each doc, classify and report checks as `OK`, `OUTDATED`, or `MISSING`.

### Universal Checks

| Check | What to verify |
|-------|---------------|
| Tool references | Mentioned tool names exist and match current names/signatures |
| Command accuracy | Commands and flags match current runtime behavior |
| Version mentions | Explicit versions align with current source/package where appropriate |
| File paths | Referenced paths exist and are correct |
| Feature behavior | Described behavior matches real auth/transport/rate-limit behavior |

### By Doc Purpose

Install docs (`INSTALL-*`):
- HTTP and STDIO setup paths are both accurate where documented
- Docker examples match current `Dockerfile` behavior
- Key/auth instructions are correct for local vs exposed use
- Platform-specific commands (PowerShell/Linux shell) are valid

Acknowledgments:
- Names/sections remain intentional and not stale references to removed project parts
- No technical claims that conflict with current code behavior

### Cross-Doc Consistency

| Check | What to verify |
|-------|---------------|
| Terminology | Same naming for tools/transports across install docs |
| Auth language | Key requirements are consistent across platform-specific docs |
| Path references | Paths and config locations are consistent across docs |

---

## Step 4: Generate Report

```
=== SUPPORTING DOCS SYNC REPORT ===
Generated: [date]

[doc-file]
  Tool references ............ OK / OUTDATED / MISSING
  Command accuracy ........... OK / OUTDATED / MISSING
  Version mentions ........... OK / OUTDATED / MISSING
  Path references ............ OK / OUTDATED / MISSING
  Feature behavior ........... OK / OUTDATED / MISSING

(repeat for each discovered doc)

Cross-Doc Consistency
  Terminology ................. OK / CONFLICT
  Auth language ............... OK / CONFLICT
  Path references ............. OK / CONFLICT

---
SUMMARY
  Outdated: [count]
  Missing: [count]
  OK: [count]

Would you like me to apply these updates? (yes/no/specific items)
```

---

## Step 5: Apply Updates (if requested)

1. Apply surgical edits only to requested docs.
2. Preserve tone and structure of each doc.
3. Update `marm-mcp-server/marm-docs/QUICK-INSTALL.md` only when install behavior changes and mirror update is needed.
4. Do not update `CHANGELOG.md` unless explicitly asked.
5. Summarize changes per file with exact paths.

---

## Important Rules

- Never rewrite entire docs unless explicitly asked.
- Prefer minimal edits with high signal.
- Flag ambiguous cases before editing.
- Treat implementation files as source of truth.
- Skip archived/future docs unless requested.
- Do not reintroduce removed features or stale transport behavior.
