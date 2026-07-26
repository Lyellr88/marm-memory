"""Compatibility server entry point and canonical marm-memory product CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

import structlog
import uvicorn

from .config import settings
from .config.settings import (
    DEFAULT_DB_PATH,
    SCHEDULER_AVAILABLE,
    SEMANTIC_SEARCH_AVAILABLE,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_VERSION,
)
from .core.rate_limiter import rate_limiter
from .utils.dependency_check import check_dependencies
from .utils.security import generate_api_key

logger = structlog.get_logger()


def _write_generated_api_key() -> None:
    """Write a newly generated key directly to the requesting terminal."""
    sys.stdout.write(f"{generate_api_key()}\n")
    sys.stdout.write(
        "\nSet this as your MARM_API_KEY environment variable.\n"
        "Keep it secret - this is the only time it will be shown.\n"
    )


async def run_server_with_shutdown() -> None:
    """Run the HTTP server with MARM's shared graceful-shutdown path."""
    from .core.shutdown_manager import shutdown_manager
    from .server import app

    shutdown_manager.shutdown_event = asyncio.Event()
    shutdown_manager.shutdown_initiated = False
    shutdown_manager._cleanup_complete = False
    await shutdown_manager.setup_signal_handlers()
    server = uvicorn.Server(
        uvicorn.Config(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
    )
    server_task = asyncio.create_task(server.serve())
    shutdown_task = asyncio.create_task(shutdown_manager.wait_for_shutdown())
    done, _pending = await asyncio.wait(
        [server_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
    )
    graceful_shutdown_signaled = shutdown_task in done
    if graceful_shutdown_signaled:
        logger.info("Shutdown signal received, closing server")
        server.should_exit = True
        await server_task
    for task in (shutdown_task,):
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if server_task in done and not graceful_shutdown_signaled:
        await server_task
    if graceful_shutdown_signaled:
        logger.info("Server shutdown complete")


def create_server():
    """Return the FastAPI app instance for external use."""
    from .server import app

    return app


def apply_runtime_preset(
    *,
    swarm: bool = False,
    swarm_max: bool = False,
    trusted: bool = False,
    rate_limit_rpm: Optional[int] = None,
) -> dict:
    """Apply CLI rate-limit/write-queue presets to imported runtime modules."""
    from .core import memory as memory_module

    if rate_limit_rpm is not None and rate_limit_rpm < 0:
        raise ValueError("--rate-limit-rpm must be 0 or greater")
    rpm = settings.MARM_RATE_LIMIT_RPM
    mode = "default"
    write_queue_enabled = settings.WRITE_QUEUE_ENABLED
    if swarm:
        rpm, mode, write_queue_enabled = 200, "swarm", True
    if swarm_max:
        rpm, mode, write_queue_enabled = 600, "swarm-max", True
    if rate_limit_rpm is not None:
        rpm, mode = rate_limit_rpm, "custom"
    if trusted:
        rpm, mode, write_queue_enabled = 0, "trusted", True
    if "COMPACTION_TRIGGER_COUNT" in os.environ:
        compaction_trigger_count = settings.COMPACTION_TRIGGER_COUNT
    else:
        compaction_trigger_count = 5 if mode == "default" else 20
    settings.MARM_RATE_LIMIT_RPM = rpm
    settings.WRITE_QUEUE_ENABLED = write_queue_enabled
    settings.COMPACTION_TRIGGER_COUNT = compaction_trigger_count
    memory_module.WRITE_QUEUE_ENABLED = write_queue_enabled
    memory_module.COMPACTION_TRIGGER_COUNT = compaction_trigger_count
    rate_limiter.configure(
        requests=rpm,
        window=settings.RATE_LIMIT_WINDOW_SECONDS,
        block_duration=settings.RATE_LIMIT_BLOCK_SECONDS,
    )
    return {
        "mode": mode,
        "rate_limit_rpm": rpm,
        "write_queue_enabled": write_queue_enabled,
    }


def _add_profile_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        choices=("standard", "swarm", "swarm-max", "trusted"),
        default="standard",
    )
    parser.add_argument(
        "--rate-limit-rpm",
        type=int,
        help="Override HTTP rate limit RPM; 0 disables rate limiting",
    )


def _add_docker_run_arguments(parser: argparse.ArgumentParser) -> None:
    _add_profile_arguments(parser)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".marm")
    parser.add_argument("--name", default="marm-mcp-server")
    parser.add_argument("--tag", default="latest")
    parser.add_argument("--repo", type=Path, action="append", default=[])
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--expose-network", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--memory")
    parser.add_argument("--cpus")


def _product_help() -> str:
    """Return the stable, human-oriented root help for the product CLI."""
    from .services.product_help import render_product_help

    return render_product_help(SERVER_VERSION)


class _ProductArgumentParser(argparse.ArgumentParser):
    """Keep root help stable while retaining argparse for all subcommands."""

    def format_help(self) -> str:
        return _product_help()


def _product_parser() -> argparse.ArgumentParser:
    parser = _ProductArgumentParser(
        prog="marm-memory",
        description="Run and manage marm-memory locally",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help", help="Show help")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=SERVER_VERSION,
        help="Show installed version",
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=argparse.ArgumentParser
    )

    start = subparsers.add_parser("start", help="Start the local MARM runtime")
    _add_profile_arguments(start)
    start.add_argument("--foreground", action="store_true")
    start.add_argument("--runtime-id", help=argparse.SUPPRESS)

    fast_start = subparsers.add_parser(
        "fast-start-http", help="Start HTTP, Console, and optional client setup"
    )
    _add_profile_arguments(fast_start)
    fast_start.add_argument("--client", help="Configure a supported MCP client")
    fast_start.add_argument("--no-console", action="store_true")
    fast_start.add_argument("--no-browser", action="store_true")

    http = subparsers.add_parser(
        "http", help="Run the HTTP transport in the foreground"
    )
    _add_profile_arguments(http)
    http.add_argument("--runtime-id", help=argparse.SUPPRESS)
    http.set_defaults(foreground=True)

    subparsers.add_parser("stdio", help="Run the MCP STDIO transport")

    stop = subparsers.add_parser("stop", help="Stop the managed MARM runtime")
    stop.add_argument("--force", action="store_true")
    restart = subparsers.add_parser("restart", help="Restart the managed runtime")
    restart.add_argument("--force", action="store_true")
    status = subparsers.add_parser("status", help="Show local MARM status")
    status.add_argument("--json", action="store_true", dest="as_json")
    console = subparsers.add_parser("console", help="Launch MARM Console")
    browser = console.add_mutually_exclusive_group()
    browser.add_argument("--open", action="store_true", dest="open_browser")
    browser.add_argument("--no-open", action="store_false", dest="open_browser")
    console.set_defaults(open_browser=True)
    console.add_argument("--foreground", action="store_true")
    console.add_argument(
        "--import-key",
        action="store_true",
        help="Create a managed authenticated Console browser session",
    )
    logs = subparsers.add_parser("logs", help="Read managed runtime logs")
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--lines", type=int, default=100)
    doctor = subparsers.add_parser("doctor", help="Diagnose the local install")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    knowledge = subparsers.add_parser("knowledge", help="Manage concept extraction")
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_command", required=True)
    knowledge_sub.add_parser("status")
    build = knowledge_sub.add_parser("build")
    scope = build.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", dest="search_all")
    scope.add_argument("--session")
    scope.add_argument("--project")

    projects = subparsers.add_parser("projects", help="Manage code indexes")
    projects_sub = projects.add_subparsers(dest="projects_command", required=True)
    projects_sub.add_parser("list")
    index = projects_sub.add_parser("index")
    index.add_argument("path")
    index.add_argument(
        "--mode", choices=("fast", "moderate", "full"), default="moderate"
    )
    project_status = projects_sub.add_parser("status")
    project_status.add_argument("project", nargs="?")
    remove = projects_sub.add_parser("remove")
    remove.add_argument("project")
    remove.add_argument("--confirm", required=True)

    maintenance = subparsers.add_parser("maintenance")
    maintenance_sub = maintenance.add_subparsers(
        dest="maintenance_command", required=True
    )
    maintenance_status = maintenance_sub.add_parser("status")
    maintenance_status.add_argument("--json", action="store_true", dest="as_json")
    embeddings = maintenance_sub.add_parser("embeddings")
    embeddings_sub = embeddings.add_subparsers(dest="embeddings_command", required=True)
    embeddings_sub.add_parser("migrate")

    key = subparsers.add_parser("key", help="Manage local bearer authentication")
    key_sub = key.add_subparsers(dest="key_command", required=True)
    key_sub.add_parser("generate", help="Generate and display an ephemeral key")
    key_sub.add_parser("init", help="Create or reuse the managed local key file")
    key_sub.add_parser("path", help="Print the managed local key-file path")
    key_sub.add_parser("reveal", help="Display the managed local key")

    from .services.docker_cli import add_docker_commands

    add_docker_commands(subparsers, _add_docker_run_arguments)
    upgrade = subparsers.add_parser(
        "upgrade", aliases=["update"], help="Check for and install a newer MARM release"
    )
    upgrade.add_argument("--check", action="store_true")
    upgrade.add_argument("--version")
    upgrade.add_argument("--yes", action="store_true")
    upgrade.add_argument("--json", action="store_true", dest="as_json")

    uninstall = subparsers.add_parser(
        "uninstall", help="Remove MARM while preserving user data"
    )
    uninstall.add_argument("--yes", action="store_true")

    init = subparsers.add_parser(
        "init", help="Install the MARM skill into detected agents"
    )
    from .services.skill_install import AGENTS

    for agent in AGENTS:
        init.add_argument(
            f"--g-{agent}",
            action="store_true",
            dest=f"global_{agent}",
            help=f"Install into the home-folder {agent} directory",
        )

    subparsers.add_parser("version", help="Show installed version")
    return parser


def _compatibility_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MARM MCP Server")
    parser.add_argument("--check-deps", action="store_true")
    parser.add_argument("--generate-key", action="store_true")
    parser.add_argument("--swarm", action="store_true")
    parser.add_argument("--swarm-max", action="store_true")
    parser.add_argument("--trusted", action="store_true")
    parser.add_argument("--rate-limit-rpm", type=int)
    parser.add_argument("--migrate-embeddings", action="store_true")
    return parser


def _profile_flags(profile: str) -> dict[str, bool]:
    return {
        "swarm": profile == "swarm",
        "swarm_max": profile == "swarm-max",
        "trusted": profile == "trusted",
    }


def _run_foreground(
    *, profile: str, rate_limit_rpm: int | None, runtime_id: str | None = None
) -> None:
    from .core.runtime_manager import (
        clear_state,
        log_path,
        make_state,
        start_log_maintenance,
        write_state,
    )

    identity = runtime_id or str(uuid.uuid4())
    os.environ["MARM_RUNTIME_ID"] = identity
    os.environ["MARM_RUNTIME_PROFILE"] = profile
    runtime_config = apply_runtime_preset(
        **_profile_flags(profile), rate_limit_rpm=rate_limit_rpm
    )
    write_state(
        make_state(
            runtime_id=identity,
            profile=profile,
            rate_limit_rpm=rate_limit_rpm,
        )
    )
    start_log_maintenance(log_path())
    try:
        _log_startup(runtime_config)
        asyncio.run(run_server_with_shutdown())
    finally:
        clear_state(identity)


def _log_startup(runtime_config: dict) -> None:
    base_url = f"http://{SERVER_HOST}:{SERVER_PORT}"
    logger.info(
        "Starting MARM MCP Server",
        version=SERVER_VERSION,
        mcp_endpoint=f"{base_url}/mcp",
        docs=f"{base_url}/docs",
        database=DEFAULT_DB_PATH,
        rate_limit_mode=runtime_config["mode"],
        rate_limit_rpm=runtime_config["rate_limit_rpm"],
        write_queue_enabled=runtime_config["write_queue_enabled"],
    )
    logger.info(
        "Feature status",
        semantic_search="ENABLED" if SEMANTIC_SEARCH_AVAILABLE else "DISABLED",
        scheduler="ENABLED" if SCHEDULER_AVAILABLE else "DISABLED",
    )


def _print_payload(payload: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(json.dumps(payload, indent=2))


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size_bytes} B"


def _queue_state(queue: dict[str, Any]) -> str:
    if not queue.get("enabled", True):
        return "disabled"
    if queue.get("stopping"):
        return "stopping"
    return "healthy" if queue.get("running") else "starting"


def _print_status(payload: dict[str, Any]) -> None:
    runtime = payload.get("runtime", {})
    metadata = runtime.get("metadata", {})
    mcp = payload.get("mcp", {})
    console = payload.get("console", {})
    memory = payload.get("memory", {})
    knowledge = payload.get("knowledge", {})
    projects = payload.get("projects", {})
    queue = payload.get("write_queue")
    print(f"MARM Memory {payload.get('version', SERVER_VERSION)}")
    print(
        f"Runtime: {runtime.get('state', 'unknown')}"
        f" | profile: {metadata.get('profile', 'standard')}"
    )
    print(
        f"MCP: {mcp.get('state', 'unknown')}"
        f" | http://127.0.0.1:{mcp.get('port', SERVER_PORT)}/mcp"
    )
    print(
        f"Console: {console.get('state', 'unknown')}"
        f" | http://127.0.0.1:{console.get('port', 8002)}"
    )
    if memory.get("error"):
        print(f"Memory: unavailable | {memory['error']}")
    elif memory.get("exists"):
        print(
            f"Memory: {memory.get('memories', 0)} records"
            f" | {memory.get('sessions', 0)} sessions"
            f" | WAL: {memory.get('wal_mode', 'unknown')}"
            f" | {_format_size(memory.get('size_bytes'))}"
        )
    else:
        print(f"Memory: no database at {memory.get('path', DEFAULT_DB_PATH)}")
    if isinstance(queue, dict):
        print(
            f"Write queue: {_queue_state(queue)}"
            f" | depth: {queue.get('depth', queue.get('queue_depth', 0))}"
        )
    else:
        print("Write queue: runtime stopped")
    print(
        f"Knowledge: {knowledge.get('state', 'unknown')}"
        f" | schema: {knowledge.get('schema', 'unknown')}"
    )
    print(f"Projects: {projects.get('state', projects.get('status', 'unknown'))}")


def _print_doctor(payload: dict[str, Any]) -> None:
    print("MARM Doctor")
    for check in payload.get("checks", []):
        marker = (
            "OK" if check.get("ok") else "WARN" if check.get("optional") else "FAIL"
        )
        print(f"[{marker}] {check.get('name')}: {check.get('detail')}")
    print()
    _print_status(payload.get("status", {}))


def _print_maintenance(payload: dict[str, Any]) -> None:
    runtime = payload.get("runtime", {})
    memory = payload.get("memory_database", {})
    embedding = payload.get("embedding", {})
    print(f"MARM Maintenance {payload.get('version', SERVER_VERSION)}")
    print(f"Runtime: {runtime.get('state', 'unknown')}")
    queue = runtime.get("write_queue")
    print(
        "Write queue: runtime stopped"
        if not isinstance(queue, dict)
        else f"Write queue: {_queue_state(queue)}"
    )
    print(
        f"Memory DB: {memory.get('path', DEFAULT_DB_PATH)}"
        f" | WAL: {memory.get('wal_mode', 'unknown')}"
        f" | {_format_size(memory.get('size_bytes'))}"
    )
    print(
        f"Embeddings: {'compatible' if embedding.get('compatible') else 'migration required'}"
        f" | {embedding.get('model', 'unknown')}"
    )


def _ensure_runtime() -> dict[str, Any]:
    from .core.runtime_manager import inspect_runtime, start_background

    current = inspect_runtime()
    return current if current["state"] == "ready" else start_background()


def _fast_start_http(args: argparse.Namespace) -> int:
    """Delegate the reusable local HTTP workflow to its service owner."""
    from .services.product_workflows import fast_start_http

    return fast_start_http(args)


def _runtime_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .core.runtime_manager import request_runtime_strict

    _ensure_runtime()
    return request_runtime_strict(path, method="POST", payload=payload, timeout=300.0)


def _migrate_embeddings() -> int:
    print("Stop every MARM HTTP and STDIO process before migrating embeddings.")
    print("STDIO processes cannot be detected reliably and must be stopped manually.")
    if _http_server_is_running():
        print(
            "Migration refused: a MARM HTTP server is still running.", file=sys.stderr
        )
        return 1
    if not Path(DEFAULT_DB_PATH).exists():
        print("No MARM memory database exists; nothing needs migration.")
        return 0
    from .utils.embedding_migration import migrate_embeddings

    try:
        result = migrate_embeddings(DEFAULT_DB_PATH)
    except Exception as exc:
        logger.error("Embedding migration failed", error=str(exc))
        print("Embedding migration failed.", file=sys.stderr)
        return 1
    print(f"Embedding migration complete: {result['rows_migrated']} vector(s) updated.")
    return 0


def _upgrade(args: argparse.Namespace) -> int:
    """Delegate package update policy to the lifecycle service."""
    from .services.product_workflows import upgrade

    return upgrade(args, print_payload=_print_payload)


def _uninstall(args: argparse.Namespace) -> int:
    """Delegate package removal policy to the lifecycle service."""
    from .services.product_workflows import uninstall

    return uninstall(args)


def _init_skill(args: argparse.Namespace) -> int:
    """Delegate skill installation to its focused service."""
    from .services.skill_install import install_skill

    return install_skill(args)


def _dispatch_product(args: argparse.Namespace) -> int:
    from .core import runtime_manager
    from .services.runtime_status import (
        doctor_status,
        full_status,
        knowledge_status,
        maintenance_status,
    )

    if args.command == "fast-start-http":
        return _fast_start_http(args)
    if args.command in {"start", "http"}:
        if args.foreground:
            _run_foreground(
                profile=args.profile,
                rate_limit_rpm=args.rate_limit_rpm,
                runtime_id=args.runtime_id,
            )
            return 0
        result = runtime_manager.start_background(
            profile=args.profile, rate_limit_rpm=args.rate_limit_rpm
        )
        state = result.get("metadata", {})
        print(
            f"MARM runtime ready: http://127.0.0.1:{state.get('port', SERVER_PORT)}/mcp"
        )
        print("Console: run `marm-memory console` when you want the web app.")
        return 0
    if args.command == "stdio":
        from . import server_stdio

        server_stdio.main()
        return 0
    if args.command == "stop":
        print(
            "MARM runtime stopped."
            if runtime_manager.stop_runtime(force=args.force)
            else "MARM runtime is not running."
        )
        return 0
    if args.command == "restart":
        current = runtime_manager.read_state() or {}
        profile = current.get("profile", "standard")
        rpm = current.get("rate_limit_rpm")
        runtime_manager.stop_runtime(force=args.force, stop_console_process=False)
        runtime_manager.start_background(profile=profile, rate_limit_rpm=rpm)
        print("MARM runtime restarted. A running Console was left available.")
        return 0
    if args.command == "status":
        payload = full_status()
        (
            _print_payload(payload, as_json=True)
            if args.as_json
            else _print_status(payload)
        )
        return 0
    if args.command == "doctor":
        payload = doctor_status()
        (
            _print_payload(payload, as_json=True)
            if args.as_json
            else _print_doctor(payload)
        )
        return 0 if payload["ok"] else 1
    if args.command == "logs":
        return _show_logs(args.lines, args.follow)
    if args.command == "console":
        _ensure_runtime()
        from .console.cli import run_console

        return run_console(
            open_browser=args.open_browser,
            foreground=args.foreground,
            import_key=args.import_key,
        )
    if args.command == "knowledge":
        if args.knowledge_command == "status":
            _print_payload(knowledge_status())
            return 0
        payload = {
            "search_all": args.search_all,
            "session_name": args.session,
            "project": args.project,
        }
        _print_payload(_runtime_post("/marm_concept_build", payload))
        return 0
    if args.command == "projects":
        return _dispatch_projects(args)
    if args.command == "maintenance":
        if args.maintenance_command == "status":
            payload = maintenance_status()
            (
                _print_payload(payload, as_json=True)
                if args.as_json
                else _print_maintenance(payload)
            )
            return 0
        return _migrate_embeddings()
    if args.command == "key":
        if args.key_command == "generate":
            _write_generated_api_key()
            return 0
        from .services import key_management

        if args.key_command == "init":
            path, created = key_management.initialize_managed_key()
            state = "Created" if created else "Using existing"
            print(f"{state} MARM API key file: {path}")
            return 0
        if args.key_command == "path":
            print(key_management.managed_key_path())
            return 0
        key = key_management.read_managed_key()
        if not key:
            print(
                "No managed MARM API key exists. Run `marm-memory key init` first.",
                file=sys.stderr,
            )
            return 1
        print(
            "Warning: terminal capture and shell history may retain this key.",
            file=sys.stderr,
        )
        print(key)
        return 0
    if args.command == "docker":
        return _dispatch_docker(args)
    if args.command in {"upgrade", "update"}:
        return _upgrade(args)
    if args.command == "uninstall":
        return _uninstall(args)
    if args.command == "init":
        return _init_skill(args)
    if args.command == "version":
        print(SERVER_VERSION)
        return 0
    return 2


def _dispatch_docker(args: argparse.Namespace) -> int:
    """Delegate Docker behavior to the shared Docker CLI service."""
    from .services.docker_cli import dispatch_docker

    return dispatch_docker(args, print_payload=_print_payload)


def _dispatch_projects(args: argparse.Namespace) -> int:
    """Delegate code-index operations to the focused project CLI service."""
    from .services.projects_cli import dispatch_projects

    return dispatch_projects(
        args,
        ensure_runtime=_ensure_runtime,
        runtime_post=_runtime_post,
        print_payload=_print_payload,
    )


def _show_logs(lines: int, follow: bool) -> int:
    """Delegate managed-log display to the focused log service."""
    from .core.runtime_manager import log_path
    from .services.product_logs import show_logs

    return show_logs(lines, follow, path=log_path())


def _dispatch_compatibility(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    if args.generate_key:
        _write_generated_api_key()
        return 0
    if args.check_deps:
        return 0 if check_dependencies() else 1
    if args.migrate_embeddings:
        return _migrate_embeddings()
    try:
        runtime_config = apply_runtime_preset(
            swarm=args.swarm,
            swarm_max=args.swarm_max,
            trusted=args.trusted,
            rate_limit_rpm=args.rate_limit_rpm,
        )
    except ValueError as exc:
        parser.error(str(exc))
    _log_startup(runtime_config)
    try:
        asyncio.run(run_server_with_shutdown())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as exc:
        logger.error("Server error", error=str(exc))
        return 1
    return 0


def main() -> None:
    """Dispatch the product CLI or preserve the legacy server command."""
    executable = Path(sys.argv[0]).name.lower()
    product_mode = executable.startswith("marm-memory") or (
        len(sys.argv) > 1
        and sys.argv[1]
        in {
            "start",
            "fast-start-http",
            "http",
            "stdio",
            "stop",
            "restart",
            "status",
            "console",
            "logs",
            "doctor",
            "knowledge",
            "projects",
            "maintenance",
            "key",
            "docker",
            "upgrade",
            "update",
            "uninstall",
            "init",
            "version",
        }
    )
    parser = _product_parser() if product_mode else _compatibility_parser()
    arguments = sys.argv[1:]
    if product_mode and arguments[:1] == ["help"]:
        if len(arguments) == 1:
            parser.print_help()
            raise SystemExit(0)
        arguments = [arguments[1], "--help", *arguments[2:]]
    args = parser.parse_args(arguments)
    if product_mode:
        try:
            code = _dispatch_product(args)
        except KeyboardInterrupt:
            print("Operation cancelled.", file=sys.stderr)
            code = 130
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            code = 1
    else:
        code = _dispatch_compatibility(args, parser)
    raise SystemExit(code)


def _http_server_is_running() -> bool:
    probe_host = SERVER_HOST
    if probe_host in {"0.0.0.0", "::", "[::]"}:
        probe_host = "127.0.0.1"
    request = urllib.request.Request(f"http://{probe_host}:{SERVER_PORT}/health")
    try:
        with urllib.request.urlopen(request, timeout=0.75):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
