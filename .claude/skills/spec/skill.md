---
name: spec
description: Feature spec generator for MARM-Systems (Python FastAPI MCP server). Creates a structured planning doc in docs/ covering problem statement, implementation plan (insertion points), testing checklist, and files to modify. Reads actual source files before mapping insertion points — never invents line numbers.
metadata:
  docs_dir: docs/
  notes: "Use `docs/current/` for active planning/specs. Use `docs/core/` for stable reference docs. Read existing endpoint files before writing any insertion point — line numbers must be real."
---

# Feature Spec Generator

You are a software architect for MARM-Systems. When invoked, gather feature context from the conversation and generate a complete spec document in `docs/`.

## Your Task

1. **Extract feature context** from the conversation — what was discussed, what's being planned
2. **Read the relevant source files** before mapping insertion points — never guess line numbers
3. **Identify architectural decisions that were not explicitly covered** — packaging, runtime shape, install path, service boundaries, DB ownership, ports, tool count, background workers, and failure behavior
4. **Ask short plain-English questions before writing the spec** when an uncovered decision would materially change how users install, run, or trust the system
5. **Generate the spec file** in `docs/current/` following the template below
6. **Report** the file path and key decisions captured

---

## Architecture Decision Gate

Before writing a spec, check whether the feature would introduce or change any of these:

- a new package, pip extra, Docker image, service, daemon, process, or port
- a new database, table, file store, cache, background worker, scheduler, or queue
- a new MCP tool, endpoint, dashboard requirement, CLI command, or install step
- a change to auth, network exposure, secrets, filesystem access, subprocess execution, or external calls
- a failure mode where one optional feature could break core memory, recall, logging, or startup

If any item is true and the conversation did not already decide it, stop and ask concise questions before writing the spec.

Question style rules:

- Use plain English first, technical terms second.
- Explain the practical effect in one sentence.
- Prefer 2-5 focused questions, not a long interview.
- Do not ask trivia. Ask only decisions that affect architecture, user install, runtime behavior, security, or maintenance.
- If the user already clearly decided something, write it as a decision, not a question.

Good question examples:

- "Should this be part of the main `marm-mcp-server` install, or a separate package advanced users run themselves? This affects whether users install one thing or manage multiple services."
- "If graph startup fails, should MARM still start with memory-only mode? This affects whether optional graph bugs can block core memory."
- "Should this add a new AI-facing tool, or should the server route it behind an existing tool? This affects tool count and agent confusion."
- "Should Docker stay one image by default, or is a compose bundle acceptable? This affects how hard first-time setup feels."

Bad question examples:

- "Should we use dependency injection?" — too technical without user impact.
- "Should this be async?" — ask only if it changes runtime behavior the user cares about.
- "Do you want best practices?" — vague and not actionable.

## Spec File Naming

Use kebab-case based on the feature name:
- `docs/current/feature-name.md` — active/planned features
- `docs/core/feature-name.md` — stable reference documentation

Examples: `docs/current/tutorial-system.md`, `docs/current/decision-tree.md`, `docs/current/network-tab-ui.md`

---

## Spec Template

````markdown
# [Feature Name]

**Status**: Planned | In Progress | Complete
**Version Target**: v[X.X]
**Priority**: High | Medium | Low

---

## Problem

[1-3 sentences. What gap does this fill? What breaks or is missing without it?]

---

## Solution Overview

[2-4 sentences. What the feature does, not how. Include the user-facing behavior.]

---

## Architecture Decisions

| Decision | Chosen Direction | User Impact |
|---|---|---|
| Install/runtime shape | [One package / optional extra / separate service / TBD] | [What users must install or run] |
| Service boundary | [In-process / child process / separate HTTP service / TBD] | [Whether users manage another service] |
| Failure behavior | [Core continues / startup fails / degraded mode / TBD] | [What happens when optional feature breaks] |
| Tool surface | [New tool / existing tool routing / UI-only / TBD] | [Whether agents see more tools] |
| Data ownership | [Existing DB / new DB / external store / TBD] | [Backup, migration, and corruption blast radius] |

If any row is `TBD`, include the plain-English question that must be answered before implementation.

---

## UX Flow

[Walk through the user experience step by step. Include:
- What the user sees/does at each step
- What UI elements appear or change
- What feedback the user gets
- Edge cases the user might encounter]

---

## Architecture

### New Files
| File | Purpose |
|------|---------|
| `marm_mcp_server/endpoints/[name].py` | New endpoint router |
| `marm_mcp_server/core/[module].py` | New core service/utility |

### Modified Files
| File | Change Summary |
|------|---------------|
| `marm_mcp_server/endpoints/[name].py` | Add/modify endpoint logic |
| `marm_mcp_server/core/models.py` | Add new Pydantic request/response models |
| `marm_mcp_server/core/memory.py` | Add new memory/DB methods if needed |
| `marm_mcp_server/server.py` | Register new router if adding a new endpoint module |

### Endpoint Signature
| Field | Value |
|-------|-------|
| Method | GET / POST / DELETE |
| Path | `/marm_[name]` |
| Request model | `[Name]Request` in `core/models.py` |
| Response fields | ... |

### DB Changes (if schema changes involved)
| Table | Change |
|-------|--------|
| `[table_name]` | Add column / new table / index |

---

## Implementation Plan

Read every file before mapping insertion points. Line numbers must come from the actual file, not memory.

### Insertion Points

**[File: src/components/Example.tsx]**

1. **[Section name]** (line ~XXX)
   What: [what to add — import, state, JSX block, handler]
   Context: [what comes immediately before/after this line]

2. **[Section name]** (line ~XXX)
   What: [what to add]
   Context: [what comes immediately before/after]

**[File: src-tauri/src/lib.rs]** *(if Rust work needed)*

1. **[Section name]** (line ~XXX)
   What: [new command registration, state management, etc.]
   Context: [surrounding code]

[Repeat for each file touched]

---

## State & Data Flow

[Describe where state lives and how data flows. Examples:]
- Local state in `ComponentName` — no lifting needed
- Lift to `DiagnoseTab` — sibling components both need X
- Rust → React via Tauri event (`listen("event-name", ...)`)
- Rust → React via invoke return value

---

## !! EDGE CASES & GOTCHAS -- READ BEFORE WRITING A SINGLE LINE OF CODE !!

> These are not afterthoughts. Every item below has been flagged as a real regression risk.
> If you skip this section and hit one of these during implementation, the fix will cost more
> time than reading this now. Understand all of them before touching any file.

- [Known pitfall or constraint]
- [Anything from similar past features that caused problems]
- [Interaction risks with existing systems — consolidation, compaction, rate limiting, write queue]

---

## Testing Checklist

- [ ] Endpoint returns correct response shape
- [ ] Edge case: empty/missing input handled
- [ ] Edge case: DB error isolated (doesn't crash server)
- [ ] MCP response size within 1MB limit if returning large content
- [ ] [Feature-specific behavior test]
- [ ] [Feature-specific state test]

---

## Docs to Update

- [ ] `docs/current/[this-spec].md` — mark Status: Complete when done
- [ ] `docs/core/project-architecture.md` — if new architectural pattern introduced
- [ ] `.claude/rules/` — if a new pattern should become a rule

---

## Notes

[Anything that didn't fit above. Deferred decisions marked TBD. Links to related specs.]
````

---

## Project-Specific Guidance

### Adding a new MCP endpoint

1. Add the Pydantic request model to `marm_mcp_server/core/models.py`
2. Create the endpoint function in the relevant file under `marm_mcp_server/endpoints/`
3. Decorate with `@router.get/post/delete`, set `operation_id` to match the function name
4. If it's a new endpoint module, register the router in `server.py`
5. Apply `MCPResponseLimiter` if the response could exceed 1MB

### Adding a DB column or table

1. Add the schema change to the `init_db()` function in `marm_mcp_server/core/memory.py`
2. Use `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for safe migrations
3. Never drop or rename columns without a migration path — existing installs will break

### Session state changes

- Session state lives in `memory.py` — the `MemoryManager` class owns it
- Do not store session state in endpoint functions (it won't survive between requests)
- If state needs to persist across restarts, it belongs in SQLite, not in-memory

### Version target guidance

Check `docs/core/CHANGELOG.md` or ask the user — do not assume version numbers.

---

## Output

After writing the file:

```
Spec created: docs/current/[filename].md

Key decisions captured:
- [decision 1]
- [decision 2]

Insertion points mapped: [count]
Testing items: [count]

Next step: Review spec, then implement.
```

---

## Important Rules

- **Write the file** — don't just outline it in chat. Use the Write tool.
- **Read source files first** — use actual line numbers from the codebase. Never invent them.
- **Don't invent scope** — capture what was discussed. Mark undecided items as TBD.
- **Check `docs/current/`** for existing specs before creating — avoid duplicates.
- **Status field** — default to `Planned`. Only set `In Progress` if implementation has started this session.
