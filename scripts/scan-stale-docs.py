#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
GRAY = "\033[90m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent
DOC_ROOT = ROOT / "docs"
PACKAGED_DOCS_ROOT = (
    ROOT / "marm-mcp-server" / "marm_mcp_server" / "resources" / "marm-docs"
)
SKIP_DOC_DIR_PREFIXES = ("docs/archived", "docs/core", "docs/current", "docs/future")
SKIP_DOC_NAMES = {"changelog.md", "contributors.md"}

REF_RE = re.compile(r"`([\w./-]+\.(?:py|md|toml|json|ts|tsx|sh|yml|yaml))`")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")

# Named by docs as files the reader creates on their own machine (MCP client
# config, editor settings), never files that live in this repo.
REF_STOPLIST = {
    ".mcp.json",
    ".cursor/mcp.json",
    ".gemini/settings.json",
    ".qwen/settings.json",
    "settings.json",
    "claude_desktop_config.json",
}

INDEX_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "dist",
    ".pytest_cache",
}


def build_file_index() -> set[str]:
    return {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*")
        if p.is_file() and not any(part in INDEX_IGNORE_DIRS for part in p.parts)
    }


def discover_docs() -> list[Path]:
    paths = [p for p in ROOT.glob("*.md") if p.name.lower() not in SKIP_DOC_NAMES]
    if DOC_ROOT.exists():
        for p in DOC_ROOT.rglob("*.md"):
            rel_posix = p.relative_to(ROOT).as_posix()
            if p.name.lower() in SKIP_DOC_NAMES:
                continue
            if any(rel_posix.startswith(prefix) for prefix in SKIP_DOC_DIR_PREFIXES):
                continue
            paths.append(p)
    if PACKAGED_DOCS_ROOT.exists():
        paths.extend(PACKAGED_DOCS_ROOT.glob("*.md"))
    server_readme = ROOT / "marm-mcp-server" / "README.md"
    if server_readme.exists():
        paths.append(server_readme)
    return sorted(set(paths), key=lambda p: str(p).lower())


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def resolve_ref(doc: Path, ref: str, index: set[str]) -> bool:
    if (doc.parent / ref).exists() or (ROOT / ref).exists():
        return True
    return any(path == ref or path.endswith(f"/{ref}") for path in index)


def check_dead_references(docs: list[Path], index: set[str]) -> int:
    print(f"{CYAN}--- Dead File References ---{RESET}")
    found = 0
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in REF_RE.finditer(line):
                ref = match.group(1)
                if "://" in ref or ref in REF_STOPLIST or resolve_ref(doc, ref, index):
                    continue
                found += 1
                print(f"  {RED}[DEAD REF]{RESET} {rel(doc)}:{lineno} -> {ref}")
    if not found:
        print(f"  {GREEN}No dead file references found.{RESET}")
    print()
    return found


def check_dead_links(docs: list[Path], index: set[str]) -> int:
    print(f"{CYAN}--- Dead Markdown Links ---{RESET}")
    found = 0
    for doc in docs:
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in LINK_RE.finditer(line):
                target = match.group(1).strip()
                if not target or target.startswith(
                    ("http://", "https://", "mailto:", "#")
                ):
                    continue
                path_part = target.split("#", 1)[0]
                if not path_part or resolve_ref(doc, path_part, index):
                    continue
                found += 1
                print(f"  {RED}[DEAD LINK]{RESET} {rel(doc)}:{lineno} -> {target}")
    if not found:
        print(f"  {GREEN}No dead links found.{RESET}")
    print()
    return found


@dataclass
class Section:
    heading: str
    start: int
    end: int


def sections_for(doc: Path) -> list[Section]:
    lines = doc.read_text(encoding="utf-8", errors="ignore").splitlines()
    headings = [
        (i + 1, m.group(2))
        for i, line in enumerate(lines)
        if (m := HEADING_RE.match(line))
    ]
    sections = []
    for idx, (start, heading) in enumerate(headings):
        end = headings[idx + 1][0] - 1 if idx + 1 < len(headings) else len(lines)
        if end >= start:
            sections.append(Section(heading, start, end))
    return sections


def last_touched(doc: Path, section: Section) -> str | None:
    proc = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%ad",
            "--date=short",
            f"-L{section.start},{section.end}:{rel(doc)}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.splitlines()[0].strip()


def check_staleness(docs: list[Path]) -> None:
    print(f"{CYAN}--- Section Staleness (by last git edit) ---{RESET}\n")
    by_doc: dict[str, list[tuple[str, str]]] = {}
    for doc in docs:
        rows = [
            (date, section.heading)
            for section in sections_for(doc)
            if (date := last_touched(doc, section))
        ]
        if rows:
            rows.sort()
            by_doc[rel(doc)] = rows

    if not by_doc:
        print(f"  {GRAY}No section history found (docs untracked?).{RESET}\n")
        return

    for doc_path in sorted(by_doc, key=lambda d: by_doc[d][0][0]):
        print(f"  {CYAN}{doc_path}{RESET}")
        for date, heading in by_doc[doc_path]:
            print(f"    {YELLOW}{date}{RESET}  {heading}")
        print()

    print(
        f"{GRAY}Files ordered by their oldest section; oldest sections listed first within each file. Review candidates, not verdicts.{RESET}\n"
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Find dead file references and links in docs; optionally show per-section git staleness."
    )
    parser.add_argument(
        "--staleness",
        action="store_true",
        help="Also show each doc section's last git-edit date, oldest first.",
    )
    args = parser.parse_args()

    print(f"{CYAN}=== Stale Docs Scan ==={RESET}\n")
    docs = discover_docs()
    index = build_file_index()

    dead_refs = check_dead_references(docs, index)
    dead_links = check_dead_links(docs, index)

    if args.staleness:
        mirrored = {PACKAGED_DOCS_ROOT, ROOT / "marm-mcp-server" / "README.md"}
        root_docs = [
            d for d in docs if PACKAGED_DOCS_ROOT not in d.parents and d not in mirrored
        ]
        check_staleness(root_docs)

    total = dead_refs + dead_links
    if total:
        print(f"{RED}{total} issue(s) found.{RESET}")
        return 1
    print(f"{GREEN}No dead references or links found.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
