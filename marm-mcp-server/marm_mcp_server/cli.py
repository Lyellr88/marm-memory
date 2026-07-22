"""Compatibility server entry point and canonical marm-memory product CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
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


def _product_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marm-memory", description="Run and manage marm-memory locally"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start the local MARM runtime")
    _add_profile_arguments(start)
    start.add_argument("--foreground", action="store_true")
    start.add_argument("--runtime-id", help=argparse.SUPPRESS)

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
    logs = subparsers.add_parser("logs", help="Read managed runtime logs")
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--lines", type=int, default=100)
    doctor = subparsers.add_parser("doctor", help="Diagnose the local install")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    knowledge = subparsers.add_parser("knowledge", help="Manage concept extraction")
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_command", required=True)
    knowledge_sub.add_parser("status")
    setup = knowledge_sub.add_parser("setup")
    setup.add_argument("--yes", action="store_true")
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

    key = subparsers.add_parser("key")
    key_sub = key.add_subparsers(dest="key_command", required=True)
    key_sub.add_parser("generate")
    subparsers.add_parser("version")
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


def _dispatch_product(args: argparse.Namespace) -> int:
    from .core import runtime_manager
    from .services.runtime_status import (
        doctor_status,
        full_status,
        knowledge_status,
        maintenance_status,
    )

    if args.command == "start":
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
        _print_payload(payload, as_json=True) if args.as_json else _print_status(
            payload
        )
        return 0
    if args.command == "doctor":
        payload = doctor_status()
        _print_payload(payload, as_json=True) if args.as_json else _print_doctor(
            payload
        )
        return 0 if payload["ok"] else 1
    if args.command == "logs":
        return _show_logs(args.lines, args.follow)
    if args.command == "console":
        _ensure_runtime()
        from .console.cli import run_console

        return run_console(open_browser=args.open_browser, foreground=args.foreground)
    if args.command == "knowledge":
        if args.knowledge_command == "status":
            _print_payload(knowledge_status())
            return 0
        if args.knowledge_command == "setup":
            from .services.knowledge_setup import install_knowledge_runtime

            confirmed = args.yes
            if not confirmed:
                preview = install_knowledge_runtime(confirmed=False)
                if preview["status"] == "ready":
                    print("Knowledge runtime is already installed.")
                    return 0
                print(f"Python environment: {preview['environment']}")
                for command in preview["commands"]:
                    print("  " + " ".join(command))
                confirmed = (
                    input("Install these dependencies? [y/N] ").strip().lower() == "y"
                )
            result = install_knowledge_runtime(confirmed=confirmed)
            _print_payload(result)
            return 0 if result["status"] in {"ready", "installed"} else 1
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
        _write_generated_api_key()
        return 0
    if args.command == "version":
        print(SERVER_VERSION)
        return 0
    return 2


def _dispatch_projects(args: argparse.Namespace) -> int:
    from .core.runtime_manager import (
        RuntimeRequestError,
        RuntimeUnavailable,
        request_runtime,
        request_runtime_strict,
    )

    _ensure_runtime()
    if args.projects_command == "list":
        payload = _runtime_post("/internal/projects/list", {})
    elif args.projects_command == "status":
        if args.project is None:
            payload = request_runtime("/internal/runtime/status") or {}
            payload = payload.get("graph", payload)
        else:
            payload = _runtime_post(
                "/internal/projects/status", {"project": args.project}
            )
    elif args.projects_command == "remove":
        if args.confirm != args.project:
            print("--confirm must exactly match the project name.", file=sys.stderr)
            return 2
        payload = _runtime_post(
            "/internal/projects/delete",
            {"project": args.project, "name": args.confirm, "confirm": True},
        )
    else:
        path = Path(args.path).expanduser()
        if not path.is_absolute() or not path.is_dir():
            print(
                "Repository path must be an existing absolute directory.",
                file=sys.stderr,
            )
            return 2
        job = _runtime_post(
            "/internal/projects/index",
            {"repo_path": str(path.resolve()), "mode": args.mode},
        )
        job_id = job.get("job_id")
        if not job_id:
            _print_payload(job)
            return 1
        poll_failures = 0
        while True:
            try:
                payload = request_runtime_strict(
                    f"/internal/projects/jobs/{job_id}", timeout=5.0
                )
                poll_failures = 0
            except RuntimeRequestError as exc:
                if exc.status_code != 429 and exc.status_code < 500:
                    raise
                poll_failures += 1
                if poll_failures >= 5:
                    raise RuntimeError(
                        "Project index status could not be read after 5 attempts."
                    ) from exc
                time.sleep(exc.retry_after or 1)
                continue
            except RuntimeUnavailable as exc:
                poll_failures += 1
                if poll_failures >= 5:
                    raise RuntimeError(
                        "Lost contact with the runtime while indexing the project."
                    ) from exc
                time.sleep(1)
                continue
            status = payload.get("status")
            if status in {"success", "error"}:
                break
            if status not in {"queued", "running"}:
                raise RuntimeError("The project index job returned an invalid status.")
            time.sleep(1)
    _print_payload(payload)
    return 1 if payload.get("status") == "error" else 0


def _show_logs(lines: int, follow: bool) -> int:
    from .core.runtime_manager import log_path

    path = log_path()
    if not path.exists():
        print("No managed runtime log exists yet.")
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        recent = deque(log_file, maxlen=max(1, lines))
        for line in recent:
            print(line, end="")
        if not follow:
            return 0
        while True:
            line = log_file.readline()
            if line:
                print(line, end="")
                continue
            try:
                if path.stat().st_size < log_file.tell():
                    log_file.seek(0)
                time.sleep(0.5)
            except KeyboardInterrupt:
                return 0
            except OSError:
                time.sleep(0.5)


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
            "version",
        }
    )
    parser = _product_parser() if product_mode else _compatibility_parser()
    args = parser.parse_args()
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
