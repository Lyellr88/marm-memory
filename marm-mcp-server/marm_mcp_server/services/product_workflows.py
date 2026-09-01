from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import Callable

from ..config import settings
from ..config.settings import SERVER_HOST, SERVER_PORT


def _port_is_available(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((probe_host, port))
            return True
        except OSError:
            return False


def fast_start_http(args: argparse.Namespace) -> int:
    """Run the intentionally small, reusable local HTTP workflow."""
    from ..core import runtime_manager
    from .runtime_status import doctor_status

    current = runtime_manager.inspect_runtime()
    if current["state"] == "stopped" and not _port_is_available(
        SERVER_HOST, SERVER_PORT
    ):
        raise RuntimeError(
            f"HTTP port {SERVER_PORT} is already in use. Run `marm-memory status` "
            "or choose a different SERVER_PORT before retrying."
        )

    preflight = doctor_status()
    warnings = [
        check["name"]
        for check in preflight["checks"]
        if not check["ok"]
        and check["name"] not in {"memory_database_parent", "mcp_port"}
    ]
    if warnings:
        print(
            "Preflight warnings: "
            + ", ".join(warnings)
            + ". Run `marm-memory doctor` for details.",
            file=sys.stderr,
        )

    from ..cli import resolve_runtime_preset

    resolved_profile, resolved_rpm = resolve_runtime_preset(
        args.profile, args.rate_limit_rpm
    )
    reused_runtime = current["state"] == "ready"
    runtime = (
        current
        if reused_runtime
        else runtime_manager.start_background(
            profile=resolved_profile, rate_limit_rpm=resolved_rpm
        )
    )
    metadata = runtime.get("metadata", {})
    runtime_port = metadata.get("port")
    runtime_profile = metadata.get("profile")
    console_url: str | None = None
    console_error: str | None = None
    if not args.no_console:
        from ..console.cli import run_console
        from .key_management import read_managed_key

        managed_auth = bool(settings.MARM_API_KEY and read_managed_key())
        try:
            run_console(
                open_browser=not args.no_browser,
                import_key=managed_auth and not args.no_browser,
            )
            console_url = (
                f"http://127.0.0.1:{os.environ.get('MARM_CONSOLE_PORT', '8002')}"
            )
        except RuntimeError as exc:
            console_error = str(exc)
            print(f"Console: unavailable ({exc})", file=sys.stderr)

    print("MARM fast start complete.")
    if runtime_port is None and reused_runtime:
        print("Runtime: managed runtime (reused; endpoint unavailable)")
    else:
        print(
            f"Runtime: http://127.0.0.1:{runtime_port or SERVER_PORT}/mcp"
            f" ({'reused' if reused_runtime else 'started'})"
        )
    if runtime_profile is None and reused_runtime:
        print("Profile: unknown (run `marm-memory status`)")
    else:
        print(f"Profile: {runtime_profile or resolved_profile}")
    print(
        "Authentication: managed key"
        if settings.MARM_API_KEY
        else "Authentication: loopback-only"
    )
    if console_url:
        print(f"Console: {console_url}")
    elif console_error:
        print("Console: unavailable")
    else:
        print("Console: skipped (--no-console)")
    print("Recovery: marm-memory doctor")
    if args.client:
        print(
            f"Client setup is not available for '{args.client}'. MARM is running; "
            "configure the client manually, then run `marm-memory status`.",
            file=sys.stderr,
        )
        return 1
    return 0


def upgrade(args: argparse.Namespace, *, print_payload: Callable[..., None]) -> int:
    """Check or upgrade a pip-managed installation without touching user data."""
    from ..core import runtime_manager
    from . import package_management
    from .runtime_status import full_status

    latest = package_management.check_latest_release()
    if args.as_json:
        if args.yes:
            raise RuntimeError("`upgrade --json` cannot be combined with `--yes`.")
        print_payload(latest, as_json=True)
        return 0
    installation = package_management.inspect_installation()
    print(f"Installed: {latest['installed_version']}")
    print(f"Latest: {latest['latest_version']}")
    print(
        "Status: already current"
        if latest["state"] == "current" and not args.version
        else "Status: update available"
    )
    if args.check:
        return 0
    if installation.editable:
        print(
            "Editable/source installations are not replaced by PyPI upgrades. "
            f"Refresh it with: {package_management.manual_upgrade_command(installation)}",
            file=sys.stderr,
        )
        return 1
    if installation.installer != "pip" or os.name == "nt":
        print(
            "This installation must be upgraded after the active launcher exits. "
            f"Run: {package_management.manual_upgrade_command(installation, args.version)}",
            file=sys.stderr,
        )
        return 1
    if latest["state"] == "current" and not args.version:
        return 0
    if not args.yes:
        print(
            "Preview only. Re-run with --yes to stop managed services, upgrade the "
            "package, and restart components that were already running."
        )
        return 0

    current_state = runtime_manager.read_state() or {}
    profile = current_state.get("profile", "standard")
    rate_limit_rpm = current_state.get("rate_limit_rpm")
    status = full_status()
    restart_runtime = status["runtime"]["state"] == "ready"
    restart_console = status["console"]["state"] == "ready"
    if restart_runtime or restart_console:
        runtime_manager.stop_runtime(stop_console_process=True)
    exit_code = package_management.run_upgrade(args.version)
    if exit_code != 0:
        if restart_runtime:
            runtime_manager.start_background(
                profile=profile, rate_limit_rpm=rate_limit_rpm
            )
        if restart_console:
            from ..console.cli import run_console

            run_console(open_browser=False)
        print(
            "Package upgrade failed; previously running components were restored.",
            file=sys.stderr,
        )
        return exit_code
    upgraded = package_management.inspect_installation()
    print(f"Upgrade complete: {upgraded.version}")
    if restart_runtime:
        runtime_manager.start_background(profile=profile, rate_limit_rpm=rate_limit_rpm)
    if restart_console:
        from ..console.cli import run_console

        run_console(open_browser=False)
    print("Run `marm-memory doctor` before any required data migration.")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    """Remove only the installed package, retaining all MARM user data."""
    from ..core import runtime_manager
    from . import package_management

    installation = package_management.inspect_installation()
    command = package_management.manual_uninstall_command(installation)
    print(f"Package: marm-mcp-server {installation.version}")
    print(f"Preserved data and configuration: {Path.home() / '.marm'}")
    if not args.yes:
        print(
            f"Preview only. Re-run with --yes to remove the package. Manual command: {command}"
        )
        return 0
    if installation.editable or installation.installer != "pip" or os.name == "nt":
        print(
            "Self-uninstall is not safe for this active launcher. Close MARM, then run: "
            f"{command}",
            file=sys.stderr,
        )
        return 1

    runtime_manager.stop_runtime(stop_console_process=True)
    exit_code = package_management.run_uninstall()
    if exit_code == 0:
        print(
            "MARM package removed. Your ~/.marm data, keys, databases, and logs were preserved."
        )
    return exit_code
