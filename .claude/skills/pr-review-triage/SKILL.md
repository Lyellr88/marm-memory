---
name: pr-review-triage
description: "GitHub PR review triage skill for MARM-Systems. Validates review comments from CodeRabbit, Codex, Dependabot, CodeQL, and human reviewers against live code, then separates must-fix issues from low-value churn so feature PRs do not get trapped in endless review loops."
---

# PR Review Triage

This skill exists to stop review churn from slowing delivery.

It is **not** a generic code-review skill. The point is not to prove every comment true or false and then fix all confirmed items. The point is to:

1. Validate review comments against the real code
2. Sort them by shipping value and release risk
3. Fix only what is worth touching in the current PR
4. Refute, defer, or ignore the rest explicitly

Use this skill when working through GitHub PR feedback from:
- CodeRabbit
- Codex GitHub reviews
- Dependabot
- CodeQL
- human review comments

Do not carry this skill across turns unless re-invoked.

---

## Mission

Keep feature delivery moving by preventing review tools from dictating scope.

This skill should reduce:
- endless AI-review loops
- fixing every confirmed nit in the feature branch
- reopening stale review batches
- mixing correctness bugs with style cleanup

This skill should increase:
- release confidence
- triage speed
- clarity on what is getting fixed now vs later

---

## Core Rule

**Confirmed does not mean worth fixing now.**

A comment must pass two gates:

1. **Truth gate**: is the issue real in the live code?
2. **Value gate**: is it important enough to fix in this PR?

Only items that pass both gates belong in the current patch set.

---

## Triage Levels

Every validated review item must be classified into one of these buckets:

### `HIGH`

Fix now.

Examples:
- correctness bugs
- race conditions
- session/data isolation leaks
- security issues
- broken tests caused by the current PR
- payload/response shape regressions
- data corruption, stale state, wrong IDs, wrong writes

### `MEDIUM`

Fix only if the patch is small, low-risk, and clearly improves release confidence.

Examples:
- brittle environment assumptions
- missing cleanup causing test flakiness
- weak idempotency shape consistency
- small diagnostics that materially improve debugging

If the fix sprawls, defer it.

### `LOW`

Do not fix in the feature PR unless explicitly told to.

Examples:
- style-only cleanup
- small refactors
- duplicate test scaffolding
- optional logging improvements
- micro-optimizations
- “consider changing defaults”
- wording/comment cleanup
- benchmark polish

These are valid backlog/deferred items, not blockers.

### `REFUTED`

The issue is false, stale, already fixed, or based on wrong assumptions.

Do not patch. Produce a clear refutation note with evidence.

---

## Default Solo-Builder Policy

Unless the user explicitly says otherwise, use this PR policy:

- `HIGH`: fix
- `MEDIUM`: fix only if surgical
- `LOW`: defer
- `REFUTED`: ignore after documenting

Do not let CodeRabbit, Codex review bots, or similar tools expand the PR beyond the feature’s real risk surface.

---

## Workflow

### 1. Read the review source

Examples:
- pasted review text
- `dump.md`
- GitHub PR comments via `gh`

If using GitHub CLI, prefer:
- `gh pr view <num> --comments`
- `gh pr view <num> --json ...`

Do not assume the latest visible review comment is the active one. Check reviewed commit ranges when possible.

### 2. Validate against live code

For each comment:
- read the exact file
- inspect surrounding control flow
- verify whether the issue is still live

Never review from memory.

### 3. Assign both verdict and level

Each item gets:
- Truth verdict: `CONFIRMED`, `REFUTED`, or `PARTIAL`
- Triage level: `HIGH`, `MEDIUM`, `LOW`

Example:
- “Confirmed, but LOW”
- “Confirmed, HIGH”
- “Refuted”

### 4. Build the action set

Split results into:
- Fix now
- Defer
- Refute

If the user wants code changes, only patch the “Fix now” set.

### 5. Keep stale review history from polluting the pass

If old review comments are still visible:
- identify them as historical/stale if commit range proves they are not current
- do not re-open already-cleared review batches

---

## What To Fix vs Skip

### Fix now

- failing tests introduced or exposed by current PR
- real race conditions
- request/response regressions
- missing session scoping
- broken idempotency
- malformed worker/task lifecycle
- schema or migration breakage
- security-sensitive file/network handling

### Usually skip

- “extract helper”
- “consider better defaults”
- “replace print with logger” unless it affects debugging of real failures
- “rename helper for clarity”
- “deduplicate scaffolding”
- benchmark/internal test polish

---

## Output Format

Use this exact structure:

```text
=== PR REVIEW TRIAGE ===
Source: [CodeRabbit / Codex / Dependabot / CodeQL / human]

FIX NOW
-------
[HIGH] File:line — Description
  Evidence: ...
  Reason: why this belongs in the current PR

[MEDIUM] ...

DEFER
-----
[LOW] File:line — Description
  Evidence: ...
  Reason: valid but not worth touching in this PR

REFUTED
-------
[REFUTED] File:line — Description
  Evidence: ...
  Reason: why the issue is false, stale, or already fixed

SUMMARY
-------
Fix now: X
Defer: Y
Refuted: Z
Recommended action: [short recommendation]
```

If the user asks for a shorter output, keep the same three buckets but compress the wording.

---

## GitHub Reply Guidance

When the user wants wording to post back on GitHub:

- For deferred items: explain they are intentionally out of scope for this PR
- For refuted items: explain the current live code and why the review assumption is stale or incorrect
- For fixed items: point to the specific behavior now present

Keep GitHub reply text short, direct, and evidence-based.

---

## Anti-Patterns

Do **not**:
- fix every confirmed review item
- reopen low-value comments after they were consciously deferred
- treat review bots as product owners
- turn a feature PR into a cleanup PR
- do speculative architecture work under the label of “review follow-up”

---

## Special Notes For MARM

When triaging MARM PR feedback, prioritize:
- memory write correctness
- session isolation
- compaction/consolidation safety
- queue behavior under contention
- HTTP/STDIO payload correctness
- test reliability for the exact changed subsystem

Be especially skeptical of comments about:
- changing defaults
- extracting shared test helpers
- “cleaner” structure with no behavior gain
- refactors that touch many files for a tiny benefit

Those are classic solo-builder time sinks.

