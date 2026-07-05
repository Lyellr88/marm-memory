---
name: pre-push
description: Local CI simulation for MARM-Systems. Mirrors the validate-and-test and build steps from publish-mcp.yml before pushing to GitHub. Catches failures locally so CI stays clean. Ends with a Docker push reminder.
metadata:
  working_dir: marm-mcp-server/
  ci_workflow: marm-mcp-server/.github/workflows/publish-mcp.yml
---

# Pre-Push CI Simulation — MARM

Run this before pushing a version tag to GitHub. Mirrors every step that CI can validate locally. Goal: zero surprises on GitHub Actions.

---

## Scope Rule

**Run this before any push that will trigger CI** — version tags (`v*`) or manual workflow dispatch.

Skip for:
- Doc-only changes
- Rules/skills/config changes
- Branches that won't trigger the publish workflow

---

## Step 1: Dependencies Check

```bash
cd marm-mcp-server
pip install -r requirements.txt
pip install pytest pytest-asyncio jsonschema requests build twine
```

- Any install failure → **blocker** (CI will fail at the same point)

---

## Step 2: Validate server.json

```bash
cd marm-mcp-server
python validate_server_json.py
```

CI runs this before every publish. If it fails here it fails on every publish job.

- Any validation error → **blocker**

---

## Step 3: Server Startup Test

```bash
cd marm-mcp-server
python -m marm_mcp_server &
sleep 5
curl -s http://localhost:8001/health
kill %1
```

Verifies the server can start and respond. CI equivalent: `timeout 10s python server.py` (note: CI uses the old path — the correct local path is `python -m marm_mcp_server`).

- Server fails to start → **blocker**
- `/health` returns non-200 → **blocker**

---

## Step 4: Run Tests

```bash
cd marm-mcp-server
pytest tests/ -v
```

**Note:** Test suite overhaul is pending (see current-issues.md). Failures here are warnings not blockers until that work is complete — use judgment on whether a failure is a real regression or a stale test.

- Known stale test failures → **warning**
- New unexpected failures → **investigate before pushing**

---

## Step 5: Build Package

```bash
cd marm-mcp-server
python -m build
```

Builds the wheel and sdist locally. Catches packaging errors — missing files, broken imports at build time, pyproject.toml issues — before PyPI sees them.

- Any build error → **blocker**
- Check `dist/` for the output: `marm_mcp_server-X.X.X-py3-none-any.whl` and `.tar.gz`

---

## Step 6: Docker Build

```bash
cd marm-mcp-server
docker build -t marm-mcp-server:local-test .
```

Builds the image locally. Catches Dockerfile issues, missing files, and broken installs inside the container before pushing to Docker Hub.

- Any build error → **blocker**
- Run a quick smoke test after build:

```bash
docker run --rm -p 8001:8001 marm-mcp-server:local-test &
sleep 8
curl -s http://localhost:8001/health
docker stop $(docker ps -q --filter ancestor=marm-mcp-server:local-test)
```

---

## Step 7: Docker Push ⚠️ Manual

```bash
docker push lyellr88/marm-mcp-server:X.X.X
docker push lyellr88/marm-mcp-server:latest
```

Replace `X.X.X` with the version from `pyproject.toml`. CI handles this automatically on tag push but verify the image is on Docker Hub before assuming the CI push succeeded.

---

## What CI Does That Can't Be Tested Locally

- **PyPI publish** — requires `PYPI_API_TOKEN` secret, handled entirely by GitHub Actions
- **MCP Registry publish** — requires GitHub OIDC authentication, only works inside GitHub Actions

Both are provider-dependent. If Steps 1–6 pass locally, these should succeed on CI.

---

## Version Consistency Check

Before pushing a version tag, verify these three agree:

```bash
grep "version" marm-mcp-server/pyproject.toml
grep -n "version" marm-mcp-server/marm_mcp_server/server.py
grep -m1 "^## " docs/core/CHANGELOG.md
```

All three should show the same version number. If they don't, fix before tagging.

---

## Output Format

```
=== PRE-PUSH CI SIMULATION: MARM ===

[STEP 1] Dependencies ................... OK / FAILED
[STEP 2] validate_server_json.py ........ OK / FAILED
[STEP 3] Server startup ................. OK / FAILED
[STEP 4] pytest ......................... X passed / X failed (see note)
[STEP 5] python -m build ................ OK / FAILED
[STEP 6] Docker build ................... OK / FAILED
         Docker smoke test .............. OK / FAILED

---
VERDICT: ✅ SAFE TO PUSH
      OR: ❌ FIX BEFORE PUSHING — [list blockers]
      OR: ⚠️  PUSH WITH AWARENESS — [list warnings]

---
REMINDER: docker push lyellr88/marm-mcp-server:X.X.X + :latest
```
