"""Verified teardown of a throwaway project from the shared engine store.

Extracted because two harnesses need it and a second, weaker copy is exactly how
one of them starts leaking projects. Both pilot.py and repro_awaited.py index into
`~/.cache/codebase-memory-mcp`, which a running MARM server is also using.

Two things here are load-bearing and neither is obvious:

Deletion goes through run_exclusive, the same cross-process lease every other
engine store mutation takes. A MARM server on this machine re-indexes watched
projects on a 30s cycle, and a throwaway project joins that watch set the moment
it is indexed, so an ungated delete can be undone by the other process.

Deletion is confirmed twice with a pause between. A single check straight after
the delete reports success it has not earned: the engine child writes its store
back a moment later, so the project reads as absent and is present again by the
time the command exits. That was observed reporting "deleted" with the database
still on disk.
"""

import subprocess
import sys
import time
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[4] / "marm-mcp-server"
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))


def engine_binary() -> Path | None:
    try:
        from codebase_memory_mcp import _cli

        return _cli._bin_path(_cli._version())
    except Exception:
        return None


def engine_cli(binary: Path, *args: str, timeout: float = 120.0) -> str:
    """Run one engine CLI command. Never raises; a timeout returns a marker.

    Bounded deliberately. Cleanup runs while holding the cross-process lease, and
    an engine call that blocks on the shared store holds it for as long as the
    call runs. With a 300s timeout and five attempts, a single teardown wedged the
    gate for eleven minutes and had to be killed.
    """
    try:
        proc = subprocess.run(
            [str(binary), "cli", *args], capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"__timeout__ after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"__error__ {exc}"
    if proc.returncode:
        detail = proc.stderr.decode(errors="replace").strip()
        return f"__error__ exit {proc.returncode}{f': {detail}' if detail else ''}"
    return proc.stdout.decode(errors="replace")


# Whole teardown budget. The lease is held for this long at worst, so it is kept
# well inside the lease TTL rather than left to the per-call timeout to bound.
_CLEANUP_BUDGET_SECONDS = 45.0
_CALL_TIMEOUT_SECONDS = 20.0


def _delete_and_confirm(binary: Path, project: str) -> str:
    deadline = time.monotonic() + _CLEANUP_BUDGET_SECONDS

    def listing() -> str:
        return engine_cli(binary, "list_projects", timeout=_CALL_TIMEOUT_SECONDS)

    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        out = engine_cli(
            binary,
            "delete_project",
            "--project",
            project,
            timeout=_CALL_TIMEOUT_SECONDS,
        )
        if out.startswith("__"):
            return f"delete failed ({out}), remove {project} by hand"
        time.sleep(1.0)
        # Confirmed twice with a gap: a single check straight after the delete
        # reports success it has not earned, because the engine child writes its
        # store back a moment later.
        first_listing = listing()
        if first_listing.startswith("__"):
            return (
                f"could not verify deletion ({first_listing}), remove {project} by hand"
            )
        if project not in first_listing:
            time.sleep(0.75)
            second_listing = listing()
            if second_listing.startswith("__"):
                return f"could not verify deletion ({second_listing}), remove {project} by hand"
            if project not in second_listing:
                return "deleted" if attempt == 1 else f"deleted after {attempt} tries"
    return f"still present after {attempt} tries, remove {project} by hand"


async def drop_project(project: str) -> str:
    """Remove a project's store. Returns a status string; "deleted" prefixes mean ok.

    Via the engine CLI because marm_graph_index exposes no delete action: its
    actions are auto/index/status/list plus the auto_* switches.
    """
    binary = engine_binary()
    if binary is None or not binary.exists():
        return "could not resolve engine binary"

    from marm_mcp_server.core.graph_index_lock import GraphIndexBusy, run_exclusive

    try:
        return await run_exclusive(
            f"cga_cleanup:{project}", _delete_and_confirm, binary, project
        )
    except GraphIndexBusy as exc:
        return f"gate busy ({exc}), remove {project} by hand"


def succeeded(status: str) -> bool:
    return status.startswith("deleted")


def report_kept(project: str | None, path: Path) -> None:
    """Say what --keep left behind, including the part that is not a directory.

    The generated files are obvious; the indexed project is not. It sits in the
    shared engine store that a running MARM also uses, so leaving it unannounced
    means it is found later as an unexplained project with a temp-directory name.
    """
    print()
    print(f"kept: files at {path}")
    if not project:
        return
    print(f"kept: graph project {project}")
    binary = engine_binary()
    location = binary if binary else "codebase-memory-mcp"
    print(f'  remove with: "{location}" cli delete_project --project {project}')
