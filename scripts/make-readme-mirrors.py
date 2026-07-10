#!/usr/bin/env python3
"""Generate the two packaged README mirrors from the root README.

Root README.md is the source of truth. This script writes:
  marm-mcp-server/README.md            PyPI variant (mcp-name header + image divs)
  marm-mcp-server/marm-docs/README.md  text-only agent-facing subset
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

src = (ROOT / "README.md").read_text(encoding="utf-8")

# ---- PyPI variant: marm-mcp-server/README.md ----
pypi = "mcp-name: io.github.Lyellr88/marm-mcp-server\n\n" + src

TOOLS_IMG = (
    '<div align="center">\n<picture>\n'
    '<img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/assets/mcp-tools.png"\n'
    '   width="700"\n   height="400"\n</picture>\n</div>\n\n'
)
BENCH_IMG = (
    '<div align="center">\n<picture>\n'
    '<img src="https://raw.githubusercontent.com/Lyellr88/MARM-Systems/MARM-main/assets/marm-bench.png"\n'
    '   width="700"\n   height="400"\n</picture>\n</div>\n\n'
)

tools_heading = "## Complete MCP Tool Suite (14 Tools)\n\n"
bench_heading = "## Performance & Scaling Benchmarks\n\n"
assert tools_heading in pypi and bench_heading in pypi, "README headings moved; update this script"
pypi = pypi.replace(tools_heading, tools_heading + TOOLS_IMG, 1)
pypi = pypi.replace(bench_heading, bench_heading + BENCH_IMG, 1)

(ROOT / "marm-mcp-server" / "README.md").write_text(pypi, encoding="utf-8")

# ---- marm-docs variant: text-only, agent-facing subset ----
lines = src.split("\n")

# Replace everything before the TOC with a plain title taken from the root h1
h1 = re.search(r"<h1[^>]*>(.*?)</h1>", src).group(1)
toc_i = lines.index("## Table of Contents")
lines = ["# " + h1, ""] + lines[toc_i:]

# Strip <div>...</div> blocks (badges/images live inside them in this file)
out = []
depth = 0
for line in lines:
    stripped = line.strip()
    if stripped.startswith("<div"):
        depth += 1
        continue
    if stripped.startswith("</div>"):
        depth = max(0, depth - 1)
        continue
    if depth == 0:
        out.append(line)
lines = out

# Drop the demo subsection (video cannot render in packaged docs)
out = []
skipping = False
for line in lines:
    if line.startswith("### MARM Demo"):
        skipping = True
        continue
    if skipping and line.startswith("## "):
        skipping = False
    if not skipping:
        out.append(line)
lines = out

# Drop non-usage sections entirely
DROP_SECTIONS = (
    "## ⭐ Star the Project",
    "## Contributing",
    "## Join the MARM Community",
    "## License & Usage Notice",
    "## Project Documentation",
)
out = []
skipping = False
for line in lines:
    if line.startswith("## "):
        skipping = line.startswith(DROP_SECTIONS)
    if not skipping:
        out.append(line)
lines = out

# Drop TOC entries pointing at removed sections
lines = [
    line
    for line in lines
    if not (
        line.startswith("- [")
        and ("#contributing" in line or "#project-documentation" in line)
    )
]

# Collapse triple+ blank lines left by removals
text = "\n".join(lines)
while "\n\n\n" in text:
    text = text.replace("\n\n\n", "\n\n")
if not text.endswith("\n"):
    text += "\n"

(ROOT / "marm-mcp-server" / "marm-docs" / "README.md").write_text(text, encoding="utf-8")
print("pypi lines:", pypi.count("\n"), "| marm-docs lines:", text.count("\n"))
