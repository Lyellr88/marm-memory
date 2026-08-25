#!/usr/bin/env python3

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

try:
    import curses

    HAS_CURSES = True
except (ImportError, ModuleNotFoundError):
    HAS_CURSES = False

SCRIPT_CATEGORIES = {
    "Benchmarking - Accuracy": [
        (
            "Code Graph: Awaited Calls",
            "benchmarking/accuracy/code-graph/awaited_calls.py",
        ),
        ("Code Graph: Pilot", "benchmarking/accuracy/code-graph/pilot.py"),
        (
            "Code Graph: Probe Units",
            "benchmarking/accuracy/code-graph/probe_code_units.py",
        ),
        (
            "Code Graph: Repro Awaited",
            "benchmarking/accuracy/code-graph/repro_awaited.py",
        ),
        (
            "Code Graph: Repro Routes",
            "benchmarking/accuracy/code-graph/repro_routes.py",
        ),
        (
            "Code Graph: Store Cleanup",
            "benchmarking/accuracy/code-graph/store_cleanup.py",
        ),
        ("LoCoMo: Run Eval", "benchmarking/accuracy/locomo/run_eval.py"),
    ],
    "Benchmarking - Performance": [
        ("Concept Worker Bench", "benchmarking/performance/bench_concept_worker.py"),
        ("Graph Scale Bench", "benchmarking/performance/bench_graph_scale.py"),
        ("Hot Path Bench", "benchmarking/performance/bench_hotpath.py"),
    ],
    "Test Scripts": [
        ("Compaction Worker Smoke", "test-scripts/compaction-worker-smoke.py"),
        ("Docker Smoke", "test-scripts/docker-smoke.py"),
        ("Smoke Commands", "test-scripts/smoke-commands.py"),
        ("Embedding Chunking Smoke", "test-scripts/smoke_embedding_chunking.py"),
        ("Hybrid Search Smoke", "test-scripts/smoke_hybrid_search.py"),
        ("Swarm Smoke", "test-scripts/swarm-smoke.py"),
        ("Write Queue HTTP Smoke", "test-scripts/write-queue-http-smoke.py"),
        ("Write Queue Smoke", "test-scripts/write-queue-smoke.py"),
    ],
    "Dev Tools": [
        ("Check File Length", "check-file-length.py"),
        ("Clean Pytest Artifacts", "clean-pytest-artifacts.py"),
        ("Dump Tool Schema", "dump_tool_schema.py"),
        ("Find Dead Code", "find-dead-code.py"),
        ("Find Tools", "find-tools.py"),
        ("Find Versions", "find-versions.py"),
        ("Run Tests", "run-tests.py"),
        ("Typecheck", "typecheck.py"),
        ("Unwrap Markdown", "unwrap-md.py"),
    ],
    "Build Tools": [
        ("Build Console", "build-console.py"),
        ("Check Console PR", "check-console-pr.py"),
        ("Release Preflight", "release-preflight.py"),
    ],
}


def get_flattened_menu() -> List[Tuple[str, str, str]]:
    """Flatten categories into (category, name, path) tuples with category headers."""
    items = []
    for category, scripts in SCRIPT_CATEGORIES.items():
        items.append((category, f"[{category}]", ""))
        for name, path in scripts:
            items.append((category, name, path))
    return items


def get_collapsed_menu(
    all_items: List[Tuple[str, str, str]], collapsed_categories: set
) -> List[Tuple[str, str, str]]:
    """Filter menu items based on collapsed categories."""
    filtered = []
    for category, name, path in all_items:
        if path == "":
            filtered.append((category, name, path))
        elif category not in collapsed_categories:
            filtered.append((category, name, path))
    return filtered


def draw_menu(
    stdscr,
    current_idx: int,
    search_query: str,
    filtered_items: List[Tuple[str, str, str]],
    collapsed_categories: set,
):
    """Draw the menu interface with collapsible categories."""
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    header = "MARM Script Launcher"
    stdscr.attron(curses.A_BOLD)
    stdscr.addstr(0, (width - len(header)) // 2, header)
    stdscr.attroff(curses.A_BOLD)

    search_line = 2
    stdscr.addstr(search_line, 2, "Search: ")
    stdscr.addstr(search_line, 10, search_query)
    stdscr.addstr(search_line, 10 + len(search_query), "_" if search_query else "")

    controls = "↑↓: Navigate | Space: Collapse | Enter: Launch | /: Search | q: Quit"
    stdscr.addstr(height - 1, 2, controls[: width - 4], curses.A_DIM)

    menu_start = 4
    menu_height = height - menu_start - 2

    scroll_offset = max(0, current_idx - menu_height // 2)

    y_pos = menu_start

    for idx, (category, name, path) in enumerate(filtered_items):
        if y_pos >= height - 2:
            break

        if idx < scroll_offset:
            continue

        is_category_header = path == ""

        if idx == current_idx:
            stdscr.attron(curses.color_pair(1))

        if is_category_header:
            collapsed = category in collapsed_categories
            indicator = "▶" if collapsed else "▼"
            if idx != current_idx:
                stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
            else:
                stdscr.attron(curses.A_BOLD)
            display_name = name.replace(f"[{category}]", f"{indicator} {category}")
            stdscr.addstr(y_pos, 2, display_name[: width - 4])
            if idx != current_idx:
                stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
            else:
                stdscr.attroff(curses.A_BOLD)
        else:
            prefix = "  "
            display_text = f"{prefix}{name}"
            if len(display_text) > width - 4:
                display_text = display_text[: width - 7] + "..."
            stdscr.addstr(y_pos, 2, display_text)

        if idx == current_idx:
            stdscr.attroff(curses.color_pair(1))

        y_pos += 1

    stdscr.refresh()


def launch_script_in_terminal(script_path: str) -> bool:
    """Run one listed development script in a new terminal window."""
    scripts_dir = Path(__file__).parent
    repo_root = scripts_dir.parent.resolve()
    known_paths = {
        path for scripts in SCRIPT_CATEGORIES.values() for _, path in scripts
    }
    if script_path not in known_paths:
        return False

    full_path = (scripts_dir / script_path).resolve()

    if not full_path.is_file() or repo_root not in full_path.parents:
        return False

    command = " ".join(
        shlex.quote(value) for value in (str(sys.executable), str(full_path))
    )
    shell_command = (
        f"cd {shlex.quote(str(repo_root))} && {command}; exec ${{SHELL:-bash}}"
    )

    def powershell_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    try:
        if sys.platform == "win32":
            ps_command = (
                f"& {powershell_quote(str(sys.executable))} "
                f"{powershell_quote(str(full_path))}"
            )
            subprocess.Popen(
                ["powershell", "-NoExit", "-Command", ps_command], cwd=repo_root
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    "on run argv\n"
                    'tell application "Terminal" to do script item 1 of argv\n'
                    "end tell\n"
                    "end run",
                    shell_command,
                ]
            )
        else:
            terminals = [
                [
                    "gnome-terminal",
                    "--working-directory",
                    str(repo_root),
                    "--",
                    "bash",
                    "-lc",
                    shell_command,
                ],
                [
                    "xterm",
                    "-e",
                    "bash",
                    "-lc",
                    shell_command,
                ],
                [
                    "konsole",
                    "--workdir",
                    str(repo_root),
                    "-e",
                    "bash",
                    "-lc",
                    shell_command,
                ],
            ]

            for term_cmd in terminals:
                try:
                    subprocess.Popen(term_cmd)
                    return True
                except FileNotFoundError:
                    continue
            return False

        return True

    except Exception as e:
        print(f"Error launching terminal: {e}")
        return False


def main(stdscr):
    """Main TUI loop with collapsible categories."""
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)

    curses.curs_set(0)

    all_items = get_flattened_menu()
    collapsed_categories = set()
    filtered_items = get_collapsed_menu(all_items, collapsed_categories)
    current_idx = 0
    search_query = ""
    search_mode = False

    while True:
        draw_menu(
            stdscr,
            current_idx,
            search_query if search_mode else "",
            filtered_items,
            collapsed_categories,
        )

        key = stdscr.getch()

        if key == ord("/"):
            search_mode = True
            search_query = ""
            continue

        if search_mode:
            if key == 27:
                search_mode = False
                search_query = ""
                filtered_items = get_collapsed_menu(all_items, collapsed_categories)
                current_idx = 0
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                search_query = search_query[:-1]
                if search_query:
                    filtered_items = [
                        item
                        for item in get_collapsed_menu(all_items, collapsed_categories)
                        if search_query.lower() in item[1].lower()
                        or search_query.lower() in item[2].lower()
                    ]
                else:
                    filtered_items = get_collapsed_menu(all_items, collapsed_categories)
                current_idx = 0
            elif key == 10:
                search_mode = False
            elif 32 <= key <= 126:
                search_query += chr(key)
                filtered_items = [
                    item
                    for item in get_collapsed_menu(all_items, collapsed_categories)
                    if search_query.lower() in item[1].lower()
                    or search_query.lower() in item[2].lower()
                ]
                current_idx = 0
            continue

        if key == curses.KEY_UP:
            current_idx = max(0, current_idx - 1)
        elif key == curses.KEY_DOWN:
            current_idx = min(len(filtered_items) - 1, current_idx + 1)
        elif key == ord(" "):
            if filtered_items:
                category, _name, path = filtered_items[current_idx]
                if path == "":
                    if category in collapsed_categories:
                        collapsed_categories.remove(category)
                    else:
                        collapsed_categories.add(category)
                    filtered_items = get_collapsed_menu(all_items, collapsed_categories)
                    if search_query:
                        filtered_items = [
                            item
                            for item in filtered_items
                            if search_query.lower() in item[1].lower()
                            or search_query.lower() in item[2].lower()
                        ]
        elif key == ord("q") or key == 27:
            if search_query:
                search_query = ""
                filtered_items = get_collapsed_menu(all_items, collapsed_categories)
                current_idx = 0
            else:
                break
        elif key == 10:
            if filtered_items:
                _category, _name, path = filtered_items[current_idx]
                if path != "":
                    launch_script_in_terminal(path)


def simple_menu():
    """Simple text-based menu fallback when curses is unavailable."""
    all_items = get_flattened_menu()

    while True:
        os.system("cls" if sys.platform == "win32" else "clear")

        print("=" * 70)
        print("MARM Script Launcher".center(70))
        print("=" * 70)
        print()

        item_number = 0
        numbered_scripts = []

        for category, name, path in all_items:
            if path == "":
                print(f"\n[{category}]")
                print("-" * 70)
            else:
                item_number += 1
                print(f"  {item_number:2d}. {name}")
                numbered_scripts.append((item_number, category, name, path))

        print()
        print("=" * 70)
        print("Enter number to launch script, 'q' to quit, or '/' to search")
        print("=" * 70)

        try:
            choice = input("\nChoice: ").strip()

            if choice.lower() == "q":
                break

            if choice == "/":
                search_query = input("Search: ").strip().lower()
                if search_query:
                    filtered = [
                        item
                        for item in all_items
                        if item[2] != ""
                        and (
                            search_query in item[1].lower()
                            or search_query in item[2].lower()
                        )
                    ]

                    if not filtered:
                        print(f"\nNo results for '{search_query}'")
                        input("Press Enter to continue...")
                        continue

                    os.system("cls" if sys.platform == "win32" else "clear")
                    print(f"\nSearch results for: {search_query}\n")

                    for idx, (category, name, _path) in enumerate(filtered, 1):
                        print(f"  {idx}. {name} ({category})")

                    sub_choice = input(
                        "\nEnter number to launch (or Enter to cancel): "
                    ).strip()

                    if sub_choice.isdigit():
                        sub_idx = int(sub_choice)
                        if 1 <= sub_idx <= len(filtered):
                            _, name, path = filtered[sub_idx - 1]
                            launch_script_in_terminal(path)

                continue

            if choice.isdigit():
                num = int(choice)
                for item_num, _category, _name, path in numbered_scripts:
                    if item_num == num:
                        launch_script_in_terminal(path)
                        break
                else:
                    print(f"\nInvalid choice: {choice}")
                    input("Press Enter to continue...")
            else:
                print(f"\nInvalid choice: {choice}")
                input("Press Enter to continue...")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break


def run_and_display_simple(script_name: str, script_path: str):
    """Launch terminal for script in simple mode."""
    print(f"\nLaunching terminal for: {script_name}")
    print(f"Path: {script_path}")

    success = launch_script_in_terminal(script_path)

    if success:
        print("\n✓ Terminal launched - command auto-typed")
        print("  Just press Enter to run (or add flags first)")
    else:
        print("\n✗ Failed to launch terminal")

    input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        if HAS_CURSES:
            curses.wrapper(main)
        else:
            print("Note: Curses not available, using simple menu mode")
            print(
                "Install windows-curses for better experience: pip install windows-curses\n"
            )
            input("Press Enter to continue...")
            simple_menu()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
