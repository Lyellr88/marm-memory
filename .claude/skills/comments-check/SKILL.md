---
name: comments-check
description: Comment hygiene reviewer for Python files. Use to identify and prune low-value comments (narration, restating obvious code) before release and to normalize section headers across Python modules with a consistent project style.
metadata:
  project: marm-mcp-server
  preferred_section_header: "two-line"
  preferred_header_example: "# Session Management / # ============================================================================"
  notes: "Manual review workflow. Read the file, identify low-value comments, remove or rewrite them. Focus on endpoints/, core/, and middleware/ modules."
---

# Comments Check

## Overview

Use this skill when you want to clean up Python comments before a release or normalize comment/header style across modules.

Review is done manually — read the target file, apply the rules below, and edit directly.

## Modes

### 1) `prune`
Removes low-value comments while keeping high-value comments (architecture, rationale, risks, workarounds, section headers, comment-based help).

Use this before launch to strip:
- narration comments ("Ensure X exists", "Warn if Y")
- inline array comments that only restate the literal value
- leftover AI-style filler notes

### 2) `style`
Normalizes section headers to the project standard:

```powershell
# 4. Parse HWiNFO CSV
# ============================================================================
```

Converts common boxed headers like:

```powershell
# ============================================================================
# 4. Parse HWiNFO CSV
# ============================================================================
```

into the two-line style above.

### 3) `both`
Runs `style` then `prune` in one pass.

## Project Comment Style Standard (Current)

### Section headers
Default section header format:

```python
# Session Management
# ============================================================================
```

Rules:
- Use one blank line before a new section header
- Do not add a blank line between the title line and divider line
- Section title should be action-oriented (`Store`, `Recall`, `Initialize`, `Validate`, `Emit`)

### Inline comments
Keep only when they add real value:
- rationale / tradeoffs
- safety constraints
- non-obvious behavior (e.g. WAL mode, embedding size limits)
- workarounds for specific bugs or library quirks

Remove when they only narrate obvious code.

## High-Value vs Low-Value Comments

Keep examples:
- Why a workaround exists
- Risk/safety notes
- Version-specific or tool-specific caveats
- Non-obvious parsing/format behavior

Remove examples:
- "Ensure reports directory exists"
- "Warn if Security log is requested without elevation"
- inline comments that restate literal values in arrays and constants (unless the mapping is non-obvious and worth preserving)

## Workflow

1. Read the target file(s) — `endpoints/`, `core/`, or `middleware/` are the main candidates.
2. Apply the high-value vs low-value rules below to identify comments to remove or rewrite.
3. Edit the file directly — remove narration comments, normalize any section headers found.
4. Report what was changed and what was kept with rationale.

## Output Expectations

The script reports per-file counts:
- section headers normalized
- standalone comments removed
- inline comments removed
- changed / unchanged

## Example Triggers

Examples that should trigger this skill:
- "Do a comment cleanup pass before release."
- "Normalize comment/header style across the endpoint files."
- "Remove AI rambling comments but keep architecture comments."
- "Make section headers consistent in the Python modules."
