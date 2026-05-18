#!/usr/bin/env python3
"""Find and optionally sync MARM version references.

The target version is derived from the final entry in CHANGELOG.md.
Changelog files are never modified because they intentionally contain many
historical version numbers.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_ROOT = PROJECT_ROOT / "marm-mcp-server"
DASHBOARD_ROOT = PROJECT_ROOT / "marm-dashboard"
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"

CRITICAL_FILES = [
    SERVER_ROOT / "marm_mcp_server" / "__init__.py",
    SERVER_ROOT / "marm_mcp_server" / "server.py",
    SERVER_ROOT / "marm_mcp_server" / "config" / "settings.py",
    SERVER_ROOT / "pyproject.toml",
    SERVER_ROOT / "server.json",
    SERVER_ROOT / "Dockerfile",
]

OCI_IDENTIFIER_FILES = [
    SERVER_ROOT / "server.json",
]

DASHBOARD_CRITICAL_FILES = [
    DASHBOARD_ROOT / "marm_dashboard" / "__init__.py",
    DASHBOARD_ROOT / "pyproject.toml",
    DASHBOARD_ROOT / "Dockerfile",
]

DOC_ROOT = PROJECT_ROOT / "docs"
MARM_DOCS_ROOT = SERVER_ROOT / "marm-docs"

VERSION_RE = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+)(?![\w.])", re.IGNORECASE)
CRITICAL_VERSION_RE = re.compile(
    r"((?:__version__|version|Version|VERSION)[\s:=\"-]+)v?(\d+\.\d+\.\d+)",
    re.IGNORECASE,
)
OCI_IDENTIFIER_RE = re.compile(
    r"(\"identifier\"\s*:\s*\"[^\"]+:)(\d+\.\d+\.\d+)(\")"
)
DOC_REPLACE_CUES = (
    "marm",
    "mcp server",
    "pip install marm-mcp-server",
    "server version",
    "git tag",
    "git push origin",
)
DOC_SKIP_CUES = (
    "fastapi",
    "sentence-transformers",
    "python-",
    "pydantic",
    "pytest",
    "black",
    "isort",
    "flake8",
    "mypy",
    "httpx",
    "torch",
    "numpy",
    "uvicorn",
)

DOC_VERSION_LINE_RE = re.compile(
    r"^.*(?:marm|mcp server|pip install marm-mcp-server|server version|"
    r"git tag|git push origin).*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VersionHit:
    version: str
    line: int
    text: str


def is_changelog(path: Path) -> bool:
    return path.name.lower() == "changelog.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def discover_docs() -> list[Path]:
    paths: list[Path] = []
    # Root-level .md files
    paths.extend(sorted(PROJECT_ROOT.glob("*.md"), key=lambda p: str(p).lower()))
    # docs/*.md
    if DOC_ROOT.exists():
        paths.extend(sorted(DOC_ROOT.glob("*.md"), key=lambda p: str(p).lower()))
    # marm-mcp-server/marm-docs/*.md
    if MARM_DOCS_ROOT.exists():
        paths.extend(sorted(MARM_DOCS_ROOT.glob("*.md"), key=lambda p: str(p).lower()))
    # marm-mcp-server/README.md
    server_readme = SERVER_ROOT / "README.md"
    if server_readme.exists():
        paths.append(server_readme)
    # marm-dashboard/README.md
    dash_readme = DASHBOARD_ROOT / "README.md"
    if dash_readme.exists():
        paths.append(dash_readme)
    return paths


def discover_dashboard_docs() -> list[Path]:
    paths: list[Path] = []
    if (DASHBOARD_ROOT / "README.md").exists():
        paths.append(DASHBOARD_ROOT / "README.md")
    return paths


def scan_versions(path: Path, pattern: re.Pattern = VERSION_RE) -> list[VersionHit]:
    hits: list[VersionHit] = []
    for line_no, line in enumerate(read_text(path).splitlines(), start=1):
        for match in pattern.finditer(line):
            version = next(
                group
                for group in match.groups()
                if group and VERSION_RE.fullmatch(group)
            )
            hits.append(
                VersionHit(
                    version=version,
                    line=line_no,
                    text=line.rstrip(),
                )
            )
    return hits


def scan_doc_versions(path: Path) -> list[VersionHit]:
    lines = read_text(path).splitlines()
    hits: list[VersionHit] = []
    for line_no, line in enumerate(lines, start=1):
        if not should_scan_doc_line(lines, line_no):
            continue
        for match in VERSION_RE.finditer(line):
            hits.append(
                VersionHit(
                    version=match.group(1),
                    line=line_no,
                    text=line.rstrip(),
                )
            )
    return hits


def should_scan_doc_line(lines: list[str], line_no: int) -> bool:
    line = lines[line_no - 1]
    line_lower = line.lower()
    nearby = "\n".join(lines[max(0, line_no - 4): min(len(lines), line_no + 3)]).lower()
    is_marm_health_version = (
        '"version"' in line_lower
        and "marm mcp server" in nearby
    )
    if not DOC_VERSION_LINE_RE.match(line) and not is_marm_health_version:
        return False
    return not any(cue in line_lower for cue in DOC_SKIP_CUES)


def latest_changelog_entry() -> str:
    if not CHANGELOG.exists():
        raise FileNotFoundError(f"Changelog not found: {CHANGELOG}")

    content = read_text(CHANGELOG)
    main_content = content.split("## \N{FILE FOLDER} Project Documentation", 1)[0]
    summary_lines = [
        line
        for line in main_content.splitlines()
        if VERSION_RE.search(line)
        and line.lstrip().startswith("<summary>")
    ]
    if summary_lines:
        return summary_lines[-1]

    heading_lines = [
        line
        for line in main_content.splitlines()
        if VERSION_RE.search(line) and line.lstrip().startswith("##")
    ]
    if not heading_lines:
        raise ValueError("No versioned changelog entries found.")
    return heading_lines[-1]


def current_version_from_changelog() -> str:
    entry = latest_changelog_entry()
    match = VERSION_RE.search(entry)
    if match:
        return match.group(1)
    raise ValueError("Final changelog entry has no version number.")


def scan_latest_changelog_versions() -> list[VersionHit]:
    entry_line = latest_changelog_entry()
    hits: list[VersionHit] = []
    for line_no, line in enumerate(read_text(CHANGELOG).splitlines(), start=1):
        if line == entry_line:
            for match in VERSION_RE.finditer(line):
                hits.append(
                    VersionHit(
                        version=match.group(1),
                        line=line_no,
                        text=line.rstrip(),
                    )
                )
            break
    return hits


def current_dashboard_version() -> str:
    init = DASHBOARD_ROOT / "marm_dashboard" / "__init__.py"
    if not init.exists():
        raise FileNotFoundError(f"Dashboard __init__.py not found: {init}")
    for line in read_text(init).splitlines():
        match = re.search(r'__version__\s*=\s*["\'](\d+\.\d+\.\d+)["\']', line)
        if match:
            return match.group(1)
    raise ValueError("No __version__ found in dashboard __init__.py")


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def print_file_hits(path: Path, hits: list[VersionHit]) -> None:
    if not hits:
        print(f"  {rel(path)} - no versions")
        return

    print(f"  {CYAN}{rel(path)}{RESET} ({len(hits)} occurrence{'s' if len(hits) != 1 else ''})")
    for hit in hits:
        print(f"    L{hit.line}: {YELLOW}{hit.version}{RESET} :: {hit.text}")


def replacement_files(dashboard: bool = False) -> list[Path]:
    critical = DASHBOARD_CRITICAL_FILES if dashboard else CRITICAL_FILES
    docs = discover_dashboard_docs() if dashboard else discover_docs()
    files: list[Path] = []
    seen: set[Path] = set()
    for path in [*critical, *docs]:
        if is_changelog(path) or not path.exists():
            continue
        resolved = path.resolve()
        if resolved not in seen:
            files.append(path)
            seen.add(resolved)
    return files


def replace_versions(path: Path, target_version: str) -> int:
    content = read_text(path)

    def broad_replacement(match: re.Match[str]) -> str:
        prefix = "v" if match.group(0).lower().startswith("v") else ""
        return f"{prefix}{target_version}"

    if path in CRITICAL_FILES or path in DASHBOARD_CRITICAL_FILES:
        updated, count = CRITICAL_VERSION_RE.subn(
            lambda match: f"{match.group(1)}{target_version}",
            content,
        )
        if path in OCI_IDENTIFIER_FILES:
            updated, oci_count = OCI_IDENTIFIER_RE.subn(
                lambda m: f"{m.group(1)}{target_version}{m.group(3)}",
                updated,
            )
            count += oci_count
    else:
        updated_lines: list[str] = []
        count = 0
        raw_lines = content.splitlines()
        lines_with_endings = content.splitlines(keepends=True)
        for line_no, line in enumerate(lines_with_endings, start=1):
            if should_scan_doc_line(raw_lines, line_no):
                line, line_count = VERSION_RE.subn(broad_replacement, line)
                count += line_count
            updated_lines.append(line)
        updated = "".join(updated_lines)

    if count:
        path.write_text(updated, encoding="utf-8", newline="")
    return count


def confirm(target_version: str, files: list[Path], assume_yes: bool) -> bool:
    if assume_yes:
        return True

    print(f"{YELLOW}Ready to replace version references with {target_version}.{RESET}")
    print(f"{YELLOW}Changelog files will be skipped.{RESET}")
    print("Files that may be updated:")
    for path in files:
        hits = (
            scan_versions(path, CRITICAL_VERSION_RE)
            if path in CRITICAL_FILES
            else scan_doc_versions(path)
        )
        if hits and any(hit.version != target_version for hit in hits):
            print(f"  - {rel(path)}")

    answer = input(
        f"\nType {target_version} to confirm, or 'y' to accept: "
    ).strip()
    return answer.lower() == "y" or answer == target_version


def prompt_target_version(changelog_version: str) -> str | None:
    while True:
        try:
            answer = input(
                f"\nUpdate versions to changelog version {changelog_version}? [y/N/c custom]: "
            ).strip().lower()
        except EOFError:
            print(f"\n{YELLOW}No input received. No changes made.{RESET}")
            return None

        if answer in {"", "n", "no"}:
            print(f"{YELLOW}No changes made.{RESET}")
            return None

        if answer in {"y", "yes"}:
            return changelog_version

        if answer in {"c", "custom"}:
            custom = input("Enter custom version (example 2.5.1): ").strip()
            if VERSION_RE.fullmatch(custom):
                return custom
            print(f"{RED}Invalid version. Use semantic version format like 2.5.1.{RESET}")
            continue

        print(f"{RED}Choose y, n, or c.{RESET}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Find MARM version references and optionally sync them interactively."
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Scan and sync the marm-dashboard package instead of the MCP server.",
    )
    args = parser.parse_args()
    dashboard: bool = args.dashboard

    try:
        if dashboard:
            target_version = current_dashboard_version()
            version_source = "marm-dashboard __init__.py"
        else:
            target_version = current_version_from_changelog()
            version_source = "final changelog entry"
    except Exception as exc:
        print(f"{RED}Could not determine current version: {exc}{RESET}")
        return 1

    label = "Dashboard" if dashboard else "MCP Server"
    print(f"{CYAN}=== MARM {label} Version Scan ==={RESET}\n")
    print(f"{GREEN}Current version from {version_source}: {target_version}{RESET}\n")

    active_critical = DASHBOARD_CRITICAL_FILES if dashboard else CRITICAL_FILES
    critical_hits: dict[Path, list[VersionHit]] = {}
    print(f"{YELLOW}Critical files:{RESET}")
    for path in active_critical:
        if not path.exists():
            print(f"  {RED}{rel(path)} - NOT FOUND{RESET}")
            continue
        hits = scan_versions(path, CRITICAL_VERSION_RE)
        if path in OCI_IDENTIFIER_FILES:
            hits = hits + scan_versions(path, OCI_IDENTIFIER_RE)
        critical_hits[path] = hits
        print_file_hits(path, hits)

    print(f"\n{YELLOW}Documentation files:{RESET}")
    doc_list = discover_dashboard_docs() if dashboard else discover_docs()
    for path in doc_list:
        hits = scan_latest_changelog_versions() if is_changelog(path) else scan_doc_versions(path)
        print_file_hits(path, hits)

    files = replacement_files(dashboard=dashboard)

    chosen_version = prompt_target_version(target_version)
    if chosen_version is None:
        return 0

    if not confirm(chosen_version, files, assume_yes=False):
        print(f"{RED}Version sync cancelled.{RESET}")
        return 1

    print()
    total = 0
    for path in files:
        count = replace_versions(path, chosen_version)
        if count:
            total += count
            print(f"{GREEN}updated {rel(path)} ({count} replacement{'s' if count != 1 else ''}){RESET}")

    print(f"\n{GREEN}Version sync complete: {total} replacements. Changelog untouched.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
