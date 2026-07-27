#!/usr/bin/env python3
"""Audit canonical MCP tool-list surfaces.

Default mode is intentionally narrow: it only reports files that are expected
to carry the full public MCP tool list or an explicit public tool count.

Use --mentions when you need the noisy "where is this tool mentioned?" view.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
GRAY = "\033[90m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent

CANONICAL_TOOLS = [
    "marm_smart_recall",
    "marm_log_entry",
    "marm_log_show",
    "marm_delete",
    "marm_summary",
    "marm_notebook",
    "marm_compaction",
    "marm_graph_index",
    "marm_code_lookup",
    "marm_graph_trace",
    "marm_graph_architecture",
    "marm_graph_impact",
    "marm_concept_build",
    "marm_concept_recall",
]

# These are the surfaces that should stay synchronized with the full public
# tool list. Files that only mention one or two tools intentionally stay out of
# the default report.
FULL_LIST_FILES = {
    "README.md",
    "docs/PROTOCOL.md",
    "docs/PROTOCOL-LITE.md",
    "marm-mcp-server/README.md",
    "marm-mcp-server/server.json",
    "marm-mcp-server/marm_mcp_server/resources/marm-docs/FAQ.md",
    "marm-mcp-server/marm_mcp_server/resources/marm-docs/PROTOCOL.md",
    "marm-mcp-server/marm_mcp_server/resources/marm-docs/PROTOCOL-LITE.md",
    "marm-mcp-server/marm_mcp_server/resources/marm-docs/README.md",
}

MENTION_SKIP_DIR_NAMES = {
    ".bridgespace",
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "marm-bot-discord",
    "marm-demo",
    "node_modules",
    "project-architecture",
}

MENTION_SKIP_PATH_PREFIXES = {
    "docs/archived",
    "docs/core",
    "docs/current",
    "docs/future",
    "marm-mcp-server/marm_mcp_server",
    "marm-mcp-server/scripts",
    "marm-mcp-server/tests",
    "scripts",
}

MENTION_EXTENSIONS = {".json", ".md", ".py", ".toml", ".txt"}

TOOL_COUNT_RE = re.compile(r"(\d+)\s+(?:focused\s+)?(?:MCP\s+)?tools?", re.IGNORECASE)
FULL_LIST_HEADING_RE = re.compile(
    r"(complete|public|surface|suite|reference|exposes)", re.IGNORECASE
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def resolve_rel(path_text: str) -> Path:
    return ROOT / Path(path_text)


def is_relevant_count_line(line: str) -> bool:
    lowered = line.lower()
    if "tool call" in lowered or "tool-call" in lowered:
        return False
    if "core mcp surface" in lowered or "core tools" in lowered:
        return False
    if "upstream" in lowered:
        return False
    return bool(FULL_LIST_HEADING_RE.search(line))


def scan_text(path: Path) -> dict:
    text = read_text(path)
    lines = text.splitlines()
    found_tools = [tool for tool in CANONICAL_TOOLS if tool in text]
    missing_tools = [tool for tool in CANONICAL_TOOLS if tool not in text]

    count_hits = []
    for lineno, line in enumerate(lines, start=1):
        if not is_relevant_count_line(line):
            continue
        for match in TOOL_COUNT_RE.finditer(line):
            count_hits.append((lineno, int(match.group(1)), line.strip()))

    return {
        "exists": path.exists(),
        "found_tools": found_tools,
        "missing_tools": missing_tools,
        "count_hits": count_hits,
    }


def scan_server_json(path: Path) -> dict:
    if not path.exists():
        return {
            "exists": False,
            "found_tools": [],
            "missing_tools": CANONICAL_TOOLS.copy(),
            "count_hits": [],
        }

    try:
        data = json.loads(read_text(path))
    except json.JSONDecodeError:
        return scan_text(path)

    tool_names = []
    for item in data.get("tools", []):
        name = item.get("name")
        if isinstance(name, str):
            tool_names.append(name)

    found_tools = [tool for tool in CANONICAL_TOOLS if tool in tool_names]
    missing_tools = [tool for tool in CANONICAL_TOOLS if tool not in tool_names]
    extra_tools = [tool for tool in tool_names if tool not in CANONICAL_TOOLS]

    return {
        "exists": True,
        "found_tools": found_tools,
        "missing_tools": missing_tools,
        "extra_tools": extra_tools,
        "count_hits": [(0, len(tool_names), '"tools" array')] if tool_names else [],
    }


def scan_full_list_file(path: Path) -> dict:
    if rel(path) == "marm-mcp-server/server.json":
        return scan_server_json(path)
    result = scan_text(path)
    result["extra_tools"] = []
    return result


def discover_mention_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        if path.name in {"CHANGELOG.md", "dump.md", "dump2.md"}:
            continue
        if any(part in MENTION_SKIP_DIR_NAMES for part in path.parts):
            continue
        rel_path = rel(path)
        if any(rel_path.startswith(prefix) for prefix in MENTION_SKIP_PATH_PREFIXES):
            continue
        if path.suffix not in MENTION_EXTENSIONS:
            continue
        files.append(path)
    return sorted(files)


def print_canonical_tools() -> None:
    print(f"{CYAN}=== MARM Tool Audit ==={RESET}")
    print(f"{GREEN}Canonical public tools ({len(CANONICAL_TOOLS)}):{RESET}")
    for index, tool in enumerate(CANONICAL_TOOLS, start=1):
        print(f"  {index}. {tool}")
    print()


def report_full_lists() -> int:
    canonical_count = len(CANONICAL_TOOLS)
    paths = [resolve_rel(path) for path in sorted(FULL_LIST_FILES)]
    failures = []

    print(f"{CYAN}--- Full Tool List Surfaces ---{RESET}")
    for path in paths:
        result = scan_full_list_file(path)
        rel_path = rel(path)

        if not result["exists"]:
            failures.append((rel_path, "missing file"))
            print(f"  {RED}[MISSING FILE]{RESET} {rel_path}")
            continue

        found = result["found_tools"]
        missing = result["missing_tools"]
        extra = result.get("extra_tools", [])
        bad_counts = [
            (lineno, count, line)
            for lineno, count, line in result["count_hits"]
            if count != canonical_count
        ]

        if missing or extra or bad_counts:
            failures.append((rel_path, "drift"))
            print(
                f"  {RED}[DRIFT]{RESET} {rel_path} ({len(found)}/{canonical_count} tools)"
            )
            for lineno, count, line in bad_counts:
                line_ref = "JSON tools array" if lineno == 0 else f"L{lineno}"
                print(
                    f"    {RED}count{RESET} {line_ref}: says {count}, want {canonical_count}"
                )
                print(f"      {GRAY}{line[:130]}{RESET}")
            for tool in missing:
                print(f"    {RED}- missing{RESET} {tool}")
            for tool in extra:
                print(f"    {RED}+ extra{RESET} {tool}")
            continue

        print(f"  {GREEN}[OK]{RESET} {rel_path} ({len(found)}/{canonical_count} tools)")

    print()
    print(f"{CYAN}--- Summary ---{RESET}")
    if failures:
        print(f"{RED}{len(failures)} full-list surface(s) need sync:{RESET}")
        for rel_path, reason in failures:
            print(f"  {rel_path} — {reason}")
        return 1

    print(f"{GREEN}All full tool-list surfaces are synchronized.{RESET}")
    return 0


def report_mentions() -> int:
    canonical_count = len(CANONICAL_TOOLS)
    files = discover_mention_files()

    print(f"{CYAN}--- Tool Mentions (Noisy Debug View) ---{RESET}")
    print(
        f"{GRAY}Scanning {len(files)} files; partial mentions are expected here.{RESET}\n"
    )

    found_any = False
    for path in files:
        result = scan_text(path)
        if not result["found_tools"]:
            continue
        found_any = True
        found = result["found_tools"]
        missing = result["missing_tools"]
        print(f"  {CYAN}{rel(path)}{RESET} ({len(found)}/{canonical_count} tools)")
        for tool in found:
            print(f"    {GREEN}+{RESET} {tool}")
        for tool in missing:
            print(f"    {GRAY}-{RESET} {tool}")

    if not found_any:
        print(f"  {GRAY}No tool mentions found.{RESET}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Audit MARM MCP tool references")
    parser.add_argument(
        "--mentions",
        action="store_true",
        help="Show all files that mention tool names, including intentional partial lists",
    )
    args = parser.parse_args()

    print_canonical_tools()
    if args.mentions:
        return report_mentions()
    return report_full_lists()


if __name__ == "__main__":
    sys.exit(main())
