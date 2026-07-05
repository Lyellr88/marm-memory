---
name: validate
description: Pre-commit code validator for MARM-Systems (Python FastAPI MCP server). Runs flake8 linting, black + isort format check, mypy type check (core/ only), debug artifact scan, and optional pytest suite (requires live server). Returns a clear PASS/FAIL verdict.
metadata:
  package_dir: marm-mcp-server/marm_mcp_server/
  core_dir: marm-mcp-server/marm_mcp_server/core/
  tests_dir: marm-mcp-server/tests/
---

# Pre-Commit Validator — MARM

Systematic validation sweep before any commit. Run all steps in order. Report results per section. End with PASS / FAIL / PASS WITH WARNINGS.

---

## Scope Rule

**Never run full validate after trivial edits** (typo fix, comment tweak, doc-only change).

Reserve for:
- New endpoints or endpoint logic changes
- Core module changes (`memory.py`, `models.py`, `response_limiter.py`)
- Middleware changes (rate limiting, error handling)
- Any change to DB schema or session state logic
- Dependency additions or version bumps

---

## Step 1: flake8 — Linting

```bash
cd marm-mcp-server && flake8 marm_mcp_server/
```

**Severity rules:**
- Any `E` error → **blocker**
- Any `F` error (undefined names, unused imports) → **blocker**
- `W` warnings → review before committing

**Common patterns to watch:**
- `F401` — unused import left in
- `E501` — line too long (88 char limit per black config)
- `F841` — local variable assigned but never used
- `E711` — comparison to None should use `is`/`is not`
- Bare `except:` without exception type → **blocker** (masks real errors)

---

## Step 2: black — Format Check

```bash
cd marm-mcp-server && black --check marm_mcp_server/
```

Non-destructive check only. If it fails, run `black marm_mcp_server/` to auto-fix, then re-check.

- Any format violation → **blocker** (auto-fix allowed)

---

## Step 3: isort — Import Order Check

```bash
cd marm-mcp-server && isort --check-only marm_mcp_server/
```

If it fails, run `isort marm_mcp_server/` to auto-fix, then re-check.

- Any import order violation → **blocker** (auto-fix allowed)

---

## Step 4: mypy — Type Check (core/ only)

```bash
cd marm-mcp-server && mypy marm_mcp_server/core/
```

Scoped to `core/` only — `memory.py`, `models.py`, `response_limiter.py`, `events.py`.

**Note:** `endpoints/` and `middleware/` are excluded intentionally. Return type annotations on endpoint functions are not yet required. See current-issues.md for the plan to expand this.

- Any type error in `core/` → **blocker**
- Missing annotation warnings in `core/` → review (may be pre-existing)

---

## Step 5: Debug Artifacts & Incomplete Work

Scan modified files:

**Blockers — remove before commit:**
```
print(          ← debug output (use structlog instead)
breakpoint()    ← debugger left in
raise NotImplementedError
```

**Warnings — review before commit:**
```
# TODO:
# FIXME:
# HACK:
except:         ← bare except (should be except Exception:)
```

**Acceptable:**
```
logger.info(    ← structured logging is fine
logger.error(   ← fine
# TODO: in a spec or planning doc (not in source code)
```

---

## Step 6: pytest — Integration Tests (optional, requires live server)

**Prerequisite:** Server must be running at `http://localhost:8001`

```bash
cd marm-mcp-server && pytest tests/ -v
```

**Skip this step if:**
- Server is not running
- Change is isolated to docs, rules, or skills
- Test suite is known broken (see current-issues.md — overhaul pending)

If skipped, report as `SKIPPED (server not running)` or `SKIPPED (test suite pending overhaul)`.

When tests do run, a failure is a **warning** not a blocker until the test suite overhaul is complete — tests may be stale, not the code.

---

## Output Format

```
=== PRE-COMMIT VALIDATION: MARM ===

[STEP 1] flake8 — marm_mcp_server/
  marm_mcp_server/endpoints/memory.py ......... OK
  marm_mcp_server/core/memory.py .............. 2 issue(s)
  [Issues listed with line numbers]

[STEP 2] black --check
  marm_mcp_server/ ............................ OK / X file(s) would reformat

[STEP 3] isort --check-only
  marm_mcp_server/ ............................ OK / X file(s) would be changed

[STEP 4] mypy — marm_mcp_server/core/
  marm_mcp_server/core/memory.py .............. OK / ERROR: <message>

[STEP 5] Debug Artifacts
  Debug artifacts: [list or NONE]
  TODOs in active code: [list or NONE]

[STEP 6] pytest
  SKIPPED (server not running)
  OR: Tests: X passed / X failed / X skipped

---
VERDICT: ✅ PASS — Safe to commit
      OR: ❌ FAIL — Fix blockers before committing
      OR: ⚠️  PASS WITH WARNINGS — Review warnings, safe to commit

Blockers: [list]
Warnings: [list]
```

---

## Important Rules

- **PASS WITH WARNINGS is valid.** Warnings don't block commits — blockers do.
- **Never skip a step** because a previous step failed. Run all steps and report everything.
- **black and isort auto-fix is preferred** — run the fix command before reporting a failure.
- **After reporting verdict, do not commit automatically.** Use `/commit` to commit.
- **pytest failures are warnings** until the test suite overhaul is complete — do not block commits on stale tests.
- **mypy is scoped to core/ only** — do not run it against endpoints/ or middleware/.
