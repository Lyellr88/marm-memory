"""Terminal-aware root help rendering for the marm-memory product CLI."""

from __future__ import annotations

import shutil
import textwrap


def render_product_help(version: str) -> str:
    """Render stable grouped help without adding a terminal UI dependency.

    Layout surfaces each command's common flags inline so users do not have to
    run `<command> --help` just to discover them; full per-command detail still
    lives in the subcommand help.
    """
    width = min(100, max(72, shutil.get_terminal_size(fallback=(100, 24)).columns))

    def section(title: str, entries: tuple[tuple[str, str], ...]) -> list[str]:
        label_width = min(38, max(len(command) for command, _ in entries) + 2)
        desc_width = max(24, width - 2 - label_width)
        lines = [title]
        for command, description in entries:
            wrapped = textwrap.wrap(
                description,
                width=desc_width,
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""]
            indent = " " * (2 + label_width)
            if len(command) < label_width:
                lines.append(f"  {command:<{label_width}}{wrapped[0]}")
                lines.extend(indent + line for line in wrapped[1:])
            else:
                lines.append(f"  {command}")
                lines.extend(indent + line for line in wrapped)
        return lines

    sections = (
        (
            "Common Options:",
            (
                ("-h, --help", "Show help for any command"),
                ("-V, --version", "Show installed version"),
                ("--json", "Machine-readable output (status, doctor, upgrade, maintenance)"),
                ("--profile <name>", "standard | swarm | swarm-max | trusted"),
            ),
        ),
        (
            "Daily Use:",
            (
                (
                    "start [--profile] [--foreground]",
                    "Start the HTTP server in the background (managed)",
                ),
                ("stop [--force]", "Stop the managed runtime safely"),
                ("restart [--force]", "Restart while preserving the selected profile"),
                ("status [--json]", "Show runtime, memory, Console, and graph status"),
                ("console [--no-open] [--import-key]", "Launch the bundled local Console"),
                ("logs [--follow] [--lines N]", "Read or follow bounded runtime logs"),
                (
                    "fast-start-http [--client] [--no-console]",
                    "Start HTTP, Console, and optional client setup",
                ),
            ),
        ),
        (
            "Run in Foreground:",
            (
                (
                    "http [--profile]",
                    "Run the HTTP server in the foreground (same as start --foreground)",
                ),
                (
                    "stdio",
                    "Run the STDIO transport for a client that launches MARM itself; "
                    "for a persistent background server use start",
                ),
            ),
        ),
        (
            "Setup and Updates:",
            (
                ("doctor [--json]", "Diagnose dependencies and configuration"),
                ("key <generate|init|path|reveal>", "Manage local bearer authentication"),
                (
                    "upgrade|update [--check] [--yes]",
                    "Check for and install a newer MARM release",
                ),
                ("uninstall [--yes]", "Remove MARM while preserving user data"),
            ),
        ),
        (
            "Knowledge and Projects:",
            (
                (
                    "knowledge status | build [--all|--session|--project]",
                    "Inspect and build the concept graph",
                ),
                (
                    "projects list | index <path> | status | remove",
                    "Index, inspect, and remove code projects",
                ),
            ),
        ),
        (
            "Docker:",
            (
                (
                    "docker <pull|run|command|compose|status|logs|stop>",
                    "Pull, run, inspect, and maintain official images",
                ),
            ),
        ),
        (
            "Maintenance:",
            (
                ("maintenance status [--json]", "Inspect persistent data"),
                ("maintenance embeddings migrate", "Re-embed after a model change"),
                ("version", "Show installed version"),
            ),
        ),
    )
    lines = [
        f"MARM Memory {version}",
        "Local-first persistent memory and code intelligence for AI agents.",
        "",
        "Usage: marm-memory <command> [options]",
        "",
    ]
    for title, entries in sections:
        lines.extend(section(title, entries))
        lines.append("")
    lines.extend(
        (
            "Examples:",
            "  marm-memory fast-start-http",
            "  marm-memory start --profile swarm",
            "  marm-memory console --import-key",
            "  marm-memory doctor",
            "  marm-memory upgrade --check",
            "",
            "Run `marm-memory <command> --help` for full options.",
        )
    )
    return "\n".join(lines) + "\n"
