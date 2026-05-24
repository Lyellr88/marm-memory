#!/usr/bin/env python3
"""Report stale or risky references in active MARM docs."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"

ROOT = Path(__file__).resolve().parent.parent
ACTIVE_DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "docs",
    ROOT / "marm-mcp-server" / "marm-docs",
]

SKIP_FILES = {"CHANGELOG.md"}
SKIP_DIR_PARTS = {"archived", "current", "future", "core", "__pycache__", ".git"}


@dataclass(frozen=True)
class StaleRule:
    name: str
    pattern: re.Pattern[str]
    note: str


RULES = [
    StaleRule(
        "websocket",
        re.compile(r"\bwebsocket\b|/mcp/ws", re.IGNORECASE),
        "Base release no longer documents WebSocket as an active client path.",
    ),
    StaleRule(
        "mock oauth",
        re.compile(r"\bmock oauth\b|/oauth/|oauth_router", re.IGNORECASE),
        "Mock OAuth was removed from the base MCP server.",
    ),
    StaleRule(
        "scrapped chatbot",
        re.compile(r"\bchatbot\b|\bwebchat\b", re.IGNORECASE),
        "Chatbot references are usually stale for the current MCP-focused release.",
    ),
    StaleRule(
        "scrapped cli",
        re.compile(r"\bmarm cli\b|\bmarm-cli\b|offline cli", re.IGNORECASE),
        "MARM CLI plan was scrapped for this release path.",
    ),
    StaleRule(
        "pinned pip install",
        re.compile(r"pip install marm-mcp-server==\d+\.\d+\.\d+", re.IGNORECASE),
        "Install docs should usually use unpinned pip install unless documenting rollback.",
    ),
    StaleRule(
        "old package version",
        re.compile(r"\b2\.2\.[0-8]\b|\b2\.3\.0\b|\b2\.4\.0\b", re.IGNORECASE),
        "May be stale outside changelog/history sections.",
    ),
    StaleRule(
        "marm_context_bridge",
        re.compile(r"\bmarm_context_bridge\b", re.IGNORECASE),
        "marm_context_bridge was removed — no longer an active tool.",
    ),
    StaleRule(
        "old context log name",
        re.compile(r"\bmarm_contextual_log\b|\bContextualLogRequest\b|\bcontextual_log\b", re.IGNORECASE),
        "Renamed to marm_context_log / ContextLogRequest in v2.6.1.",
    ),
    StaleRule(
        "split delete tools",
        re.compile(r"\bmarm_log_delete\b|\bmarm_notebook_delete\b", re.IGNORECASE),
        "Replaced by marm_delete(type='log'|'notebook') in v2.6.0.",
    ),
    StaleRule(
        "split notebook tools",
        re.compile(
            r"\bmarm_notebook_(?:add|use|show|status|clear)\b",
            re.IGNORECASE,
        ),
        "Replaced by marm_notebook(action='add'|'use'|'show'|'status'|'clear') in v2.6.1.",
    ),
    StaleRule(
        "hidden lifecycle tools",
        re.compile(r"\bmarm_start\b|\bmarm_refresh\b|\bmarm_reload_docs\b", re.IGNORECASE),
        "These are hidden/internal lifecycle endpoints now — they should not be documented as active MCP tools.",
    ),
    StaleRule(
        "removed system tools",
        re.compile(r"\bmarm_current_context\b|\bmarm_system_info\b", re.IGNORECASE),
        "Removed from the MCP tool surface. Use automatic context/protocol handling or /health/dashboard status.",
    ),
    StaleRule(
        "old tool count",
        re.compile(r"\b(?:12|18|19)\s+(?:complete\s+)?(?:focused\s+)?(?:mcp\s+)?tools\b", re.IGNORECASE),
        "Current public MCP tool surface is 8 tools.",
    ),
    StaleRule(
        "old command prompt framing",
        re.compile(r"\bcopy/paste\b|\bcopy and paste\b|\bslash command\b|\bslash-command\b", re.IGNORECASE),
        "Protocol/docs should describe MCP runtime behavior, not old chatbot/manual prompt workflows.",
    ),
]


def iter_docs() -> list[Path]:
    files: list[Path] = []
    for path in ACTIVE_DOC_PATHS:
        if path.is_file() and path.suffix.lower() == ".md":
            files.append(path)
            continue
        if not path.exists():
            continue
        for doc in path.glob("*.md"):
            if doc.name in SKIP_FILES:
                continue
            if any(part in SKIP_DIR_PARTS for part in doc.parts):
                continue
            files.append(doc)
    return sorted(set(files), key=lambda p: str(p).lower())


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print(f"{CYAN}=== Active Docs Stale Reference Scan ==={RESET}\n")
    findings: list[tuple[Path, int, StaleRule, str]] = []

    for doc in iter_docs():
        text = doc.read_text(encoding="utf-8", errors="ignore")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for rule in RULES:
                if rule.pattern.search(line):
                    findings.append((doc, line_no, rule, line.rstrip()))

    if not findings:
        print(f"{GREEN}No stale doc references found in active docs.{RESET}")
        return 0

    current_file: Path | None = None
    for doc, line_no, rule, line in findings:
        if doc != current_file:
            current_file = doc
            print(f"{YELLOW}{rel(doc)}{RESET}")
        print(f"  L{line_no}: [{rule.name}] {line}")
        print(f"       {rule.note}")

    print(f"\n{YELLOW}{len(findings)} potential stale reference(s) found. Review manually before editing.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
