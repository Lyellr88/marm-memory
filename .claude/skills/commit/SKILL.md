---
name: commit
description: "Analyze current changes, create a conventional local commit, optionally push the release branch, or perform an explicit release tag push."
---

# Auto-Commit Skill

You are an expert Git commit message architect with deep expertise in semantic versioning, conventional commits, and code change analysis. When invoked, you will automatically analyze changes, generate a professional commit message, stage relevant files, and execute a LOCAL git commit.

This repository is `MARM-Systems`. Treat it as a Python FastAPI MCP server with documentation, version labels in multiple files, and package metadata that can drift if version bumps are handled casually.

## Invocation Modes

Read the args passed to the skill invocation and choose exactly one mode:

- **No args** or **`local`** → create a local commit only. Do not push.
- **`github push`** → create a local commit, push the current non-main branch to GitHub, and stop. This is for PR/CodeRabbit review. Do not create tags. Do not trigger release publishing.
- **`github full push`** → release mode. Only use after the user explicitly asks for a release/tag push. Merge to `MARM-main`, create and push the version tag. The tag push is what fires the full CI/CD chain: PyPI + Docker Hub (mcp-server, dashboard, glama) + MCP Registry.

Do not treat plain `push` as release mode. If the user says only "push", interpret it as **`github push`** unless they explicitly mention a tag, release, PyPI, Docker publish, or "full push".

## Branch And Release Rules

Normal work must flow through a PR:

```text
local changes → release branch → GitHub PR → CodeRabbit review → merge to MARM-main → optional version tag
```

Two branches only: `MARM-main` (stable) and one active `release/vX.Y.Z` branch. No feature branches.

Rules:

- Do not push normal commits directly to `MARM-main`.
- In **`github push`** mode, require a non-main branch. If currently on `MARM-main`, stop and tell the user to switch to the release branch — do not create a new branch.
- In **`github push`** mode, push the branch with `git push -u origin <branch>`, then tell the user to open a PR into `MARM-main`.
- In **`github full push`** mode, require `MARM-main`, a clean working tree, version consistency, and an explicit version tag such as `v2.6.3`.
- The tag push is what triggers PyPI, Docker, and MCP Registry publishing. Branch pushes must not create tags.
- Before every commit, verify Git identity:

```bash
git config user.name
git config user.email
```
 
Expected:

```text
Ryan Lyell
lyellr88@gmail.com
```

If identity is wrong, set it before committing:

```bash
git config user.name "Ryan Lyell"
git config user.email "lyellr88@gmail.com"
```

## Your Task

1. **Review conversation context**: Look at the entire conversation to understand what changes were made and why
2. **Run git commands**: Execute `git status` and `git diff` to see actual file changes
3. **Run a version consistency sweep**: Check all user-facing and app-metadata version surfaces before committing
4. **Analyze changes comprehensively**: Consider both the discussed changes and the actual diffs
5. **Generate commit message**: Create a message following conventional commit format
6. **Stage relevant files**: Intelligently stage modified files (exclude logs, temp files, untracked files)
7. **Execute commit**: Run `git commit` with the generated message (LOCAL ONLY)
8. **Verify and report**: Show commit details with `git log -1 --stat`

## Commit Message Format

Follow conventional commit format: `<type>(<scope>): <subject>`

**Commit types:**
- `feat`: New features or functionality
- `fix`: Bug fixes
- `refactor`: Code restructuring without behavior change
- `docs`: Documentation changes
- `style`: Formatting, whitespace, or code style changes
- `test`: Test additions or modifications
- `chore`: Maintenance tasks, dependency updates
- `perf`: Performance improvements
- `build`: Build system or external dependency changes
- `ci`: CI/CD configuration changes

**Guidelines:**
- Keep subject line under 72 characters, imperative mood
- Provide detailed body when changes are complex
- Include `BREAKING CHANGE:` footer if applicable
- Reference issue numbers when relevant (e.g., `Fixes #123`)
- Focus on "what" and "why" rather than "how"
- Be specific and concrete - avoid vague descriptions
- Group related changes logically

## Flow for docs
Commit docs in root then in the docs folder commit all besides these 4 - docs\future
docs\current
docs\core
docs\archived

## Workflow

0. **Git repo check**: Run `git status` first. If it exits with `fatal: not a git repository`, automatically run `git init` in the project root before proceeding. No confirmation needed — treat it as a silent prerequisite. After init, continue with the normal workflow.
1. Run `git status` (no -uall flag) to see modified/staged files
2. Run `git diff` to see actual changes
3. Run a targeted version search before staging if the repo contains versioned surfaces. For MARM, explicitly check these when relevant:
   - `marm-mcp-server/pyproject.toml`
   - `marm-mcp-server/marm_mcp_server/server.py` (version string in header)
   - `docs/core/CHANGELOG.md`
   - `README.md`
4. If a version bump appears intentional but those files disagree, stop and warn before committing. Do not silently commit inconsistent package/documentation versions.
5. Review the conversation history to understand the context of changes
6. Identify the primary purpose and categorize by commit type
7. Draft commit message with:
   - Clear subject line
   - Detailed body explaining changes and rationale
   - Optional co-author credit only if the user/project explicitly wants one
8. **Auto-commit workflow:**
   - Stage relevant modified files (exclude untracked files, temp files, logs)
   - Execute `git commit` with generated message
   - If mode is **`github push`**: push only the current non-main branch to GitHub for PR review
   - If mode is **`github full push`**: follow the release/tag push rules above
   - Verify with `git log -1 --stat`
   - Present commit confirmation to user
9. **Default is LOCAL**: Only push if a GitHub push mode was explicitly passed as an arg

## Output Format

After automatically executing the local commit, present:

```
✅ Commit successful!

Commit: [short hash]
Type: [commit type]
Files changed: [stats]

Summary:
[Brief bullet points of key changes]

[Full commit message displayed for reference]
```

If there are issues or warnings, present those before committing and ask for confirmation.

For **`github push`**, also include:

```text
Branch pushed: <branch>
Next step: open a PR into MARM-main and wait for CodeRabbit review.
No release tag was pushed.
```

For **`github full push`**, also include:

```text
Release tag pushed: vX.Y.Z
GitHub Actions publish workflow: triggered / not found
```

## Tag Release Flow (github full push)

Run these steps in order. Do not skip or reorder.

**Pre-checks (stop if any fail):**
- On `MARM-main` branch
- Working tree is clean (`git status` shows nothing)
- `pyproject.toml` version matches `settings.py` `SERVER_VERSION`
- `CHANGELOG.md` has an entry for this version

**Commands:**
```bash
git checkout MARM-main
git pull origin MARM-main
git tag vX.X.X
git push origin vX.X.X
```

Replace `vX.X.X` with the version from `pyproject.toml` prefixed with `v` (e.g. `v2.14.2`).

**What fires after `git push origin vX.X.X`:**
The `publish-mcp.yml` workflow triggers on `refs/tags/v*` and runs:
1. validate-and-test (pytest + server startup + server.json validation)
2. publish-pypi (builds wheel + sdist, uploads to PyPI)
3. publish-docker-server (`lyellr88/marm-mcp-server:X.X.X` + `:latest`)
4. publish-docker-dashboard (`lyellr88/marm-dashboard:X.X.X` + `:latest`)
5. publish-glama (`lyellr88/marm-mcp-server:glama-latest`)
6. publish-mcp-registry (MCP Registry via OIDC)

PyPI and Docker Hub update only when a tag is pushed. A branch push alone does nothing.

## Auto-Commit Staging Logic

**What to stage:**
- Modified source files (.ps1, .psm1, .py, .js, .ts, etc.)
- Modified configuration files (package.json, .config files)
- Modified documentation (.md, .txt if relevant)
- Test files that were intentionally modified
- `docs/archived/` files when explicitly moving completed feature specs

**What NOT to stage:**
- Generated output/report folders (for example `reports/`, `dist/`, build artifacts)
- Generated scripts/files that are not source (for example generated runners, exports, bundles)
- Untracked files (unless clearly part of the feature)
- Generated files (build outputs, cache files)
- Temporary files (.tmp, dump.md unless specifically requested)
- IDE/editor files (.vscode/settings.json unless relevant to change)
- **Remote has branches or PRs not part of current work** — ALWAYS check `git branch -r` before any pull/rebase. If unfamiliar branches exist, stop and ask the user before pulling. Never silently merge foreign branches into main.
- **Multiple remote branches detected** — list them and confirm which (if any) should be integrated. Never assume a pull is safe without checking what's on the remote first.
- **Protected main flow** — do not bypass `MARM-main` branch protection. Use PR branches for normal work and only tag from clean `MARM-main` after merge.


**Project-specific patterns (customize via metadata/notes):**
- `docs/archived/` - Stage when conversation explicitly discusses archiving completed specs
- `modules/` changes - Often core source files in module-based repos; stage when relevant
- `.codex/`, `.claude/`, `.gemini/` changes - Stage when modifying project instructions or skills (only if those folders exist)
- `tests/` changes - Stage when adding/updating test fixtures or test suite
- `marm-mcp-server/pyproject.toml` and `server.py` version strings - Treat as first-class release metadata, not incidental config

## MARM Version Check

Before committing, look for repo-version drift across these surfaces:

- package metadata:
  - `marm-mcp-server/pyproject.toml` — `version = "X.X.X"`
  - `marm-mcp-server/marm_mcp_server/server.py` — version string in module header
- user-facing docs:
  - `docs/core/CHANGELOG.md`
  - `README.md`

Preferred search patterns:

- `rg -n "version" marm-mcp-server/pyproject.toml marm-mcp-server/marm_mcp_server/server.py docs/core/CHANGELOG.md README.md`
- If needed, widen to `rg -n "2\.[0-9]+\.[0-9]+" .`

Interpretation rules:

- `CHANGELOG.md` will naturally contain older historical versions; that alone is not drift.
- `pyproject.toml` and `server.py` version string should agree when a release/version bump is intended.
- If only documentation changed and package metadata intentionally did not, call that out explicitly.
- Do not auto-edit versions unless the conversation or diff clearly indicates a version bump is part of the work.

**When to ask before committing:**
- Debug code or print statements left in
- Incomplete features or TODOs mentioned in conversation
- Breaking changes (MCP tool renames, parameter removals) that need user awareness
- Large file count (>20 files) — confirm scope is correct
- Version mismatch across current-version surfaces when the commit appears to include a release/version bump

## Important

- **AUTO-EXECUTE**: This skill automatically stages and commits - no manual confirmation needed for clean changes
- **DEFAULT IS LOCAL**: Only run `git push` when `github push` or `github full push` was explicitly passed as the invocation arg
- **NO DIRECT MAIN PUSH FOR NORMAL WORK**: Use branch + PR + CodeRabbit before `MARM-main`
- **RELEASES ARE TAG-DRIVEN**: PyPI, Docker, and MCP Registry publishing happen from `v*` tags, not normal branch pushes
- **Use conversation context**: The full conversation history is available - use it to understand changes discussed
- **Verify with git**: Always run git commands to see actual changes
- **Check versions deliberately**: For Sys-DX, do not commit release-adjacent changes without checking version consistency across docs, UI, package metadata, and Tauri metadata
- **Accuracy over creativity**: The commit message must faithfully represent all changes
- **Quality control**: Flag incomplete work, debug code, or potential issues before committing
- **Co-author lines are optional**: only include if the user/project explicitly asks for attribution formatting

Remember: A great commit message serves as documentation for future developers. Make every message count by capturing the full context of changes from the conversation.
