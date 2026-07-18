"""CLI entrypoint for MARM MCP Server (marm-mcp-server console script)."""

import asyncio
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

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


async def run_server_with_shutdown():
    """Run server with proper signal handling and graceful shutdown"""
    from .core.shutdown_manager import shutdown_manager
    from .server import app

    await shutdown_manager.setup_signal_handlers()

    config = uvicorn.Config(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())

    shutdown_task = asyncio.create_task(shutdown_manager.wait_for_shutdown())

    done, pending = await asyncio.wait(
        [server_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
    )

    graceful_shutdown_signaled = shutdown_task in done
    if graceful_shutdown_signaled:
        logger.info("Shutdown signal received, closing server")
        await shutdown_manager.graceful_shutdown()
        server.should_exit = True

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # If server_task finished first (e.g. uvicorn crashed on startup), it's
    # in `done`, not `pending` -- awaiting it here re-raises its exception so
    # a startup failure surfaces instead of the process silently exiting 0.
    if server_task in done:
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
    """Apply CLI rate-limit/write-queue presets to already-imported runtime modules."""
    from .core import memory as memory_module

    if rate_limit_rpm is not None and rate_limit_rpm < 0:
        raise ValueError("--rate-limit-rpm must be 0 or greater")

    rpm = settings.MARM_RATE_LIMIT_RPM
    mode = "default"
    write_queue_enabled = settings.WRITE_QUEUE_ENABLED

    if swarm:
        rpm = 200
        mode = "swarm"
        write_queue_enabled = True
    if swarm_max:
        rpm = 600
        mode = "swarm-max"
        write_queue_enabled = True
    if rate_limit_rpm is not None:
        rpm = rate_limit_rpm
        mode = "custom"
    if trusted:
        rpm = 0
        mode = "trusted"
        write_queue_enabled = True

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


def main():
    """Entry point for pip-installed CLI (marm-mcp-server command)."""
    import argparse

    parser = argparse.ArgumentParser(description="MARM MCP Server")
    parser.add_argument(
        "--check-deps", action="store_true", help="Check system dependencies and exit"
    )
    parser.add_argument(
        "--generate-key",
        action="store_true",
        help="Generate a strong MARM_API_KEY and print it to stdout",
    )
    parser.add_argument(
        "--swarm",
        action="store_true",
        help="Enable shared HTTP swarm mode (write queue on, 200 RPM)",
    )
    parser.add_argument(
        "--swarm-max",
        action="store_true",
        help="Enable heavier shared HTTP swarm mode (write queue on, 600 RPM)",
    )
    parser.add_argument(
        "--trusted",
        action="store_true",
        help="Trusted local/private mode (write queue on, rate limiting disabled)",
    )
    parser.add_argument(
        "--rate-limit-rpm",
        type=int,
        help="Override HTTP rate limit RPM; 0 disables rate limiting",
    )
    parser.add_argument(
        "--migrate-embeddings",
        action="store_true",
        help="Migrate existing embeddings to the current model and exit",
    )
    args = parser.parse_args()

    if args.generate_key:
        key = generate_api_key()
        print(key)
        print("\nSet this as your MARM_API_KEY environment variable.")
        print("Keep it secret — this is the only time it will be shown.")
        sys.exit(0)

    if args.check_deps:
        success = check_dependencies()
        sys.exit(0 if success else 1)

    if args.migrate_embeddings:
        print("Stop every MARM HTTP and STDIO process before migrating embeddings.")
        print(
            "STDIO processes cannot be detected reliably and must be stopped manually."
        )
        if _http_server_is_running():
            print(
                "Migration refused: a MARM HTTP server is still running.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not Path(DEFAULT_DB_PATH).exists():
            print("No MARM memory database exists; nothing needs migration.")
            sys.exit(0)

        from .utils.embedding_migration import migrate_embeddings

        try:
            result = migrate_embeddings(DEFAULT_DB_PATH)
        except Exception as exc:
            print(f"Embedding migration failed: {exc}", file=sys.stderr)
            sys.exit(1)
        print(
            "Embedding migration complete: "
            f"{result['rows_migrated']} vector(s) updated."
        )
        sys.exit(0)

    try:
        runtime_config = apply_runtime_preset(
            swarm=args.swarm,
            swarm_max=args.swarm_max,
            trusted=args.trusted,
            rate_limit_rpm=args.rate_limit_rpm,
        )
    except ValueError as exc:
        parser.error(str(exc))

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
        semantic_search=(
            "ENABLED" if SEMANTIC_SEARCH_AVAILABLE else "DISABLED - install fastembed"
        ),
        scheduler=(
            "ENABLED" if SCHEDULER_AVAILABLE else "DISABLED - install apscheduler"
        ),
        rate_limiting=(
            "DISABLED" if runtime_config["rate_limit_rpm"] == 0 else "ENABLED"
        ),
        write_queue="ENABLED" if runtime_config["write_queue_enabled"] else "DISABLED",
    )

    print(
        "  Community: discord.gg/nhyJWPz2cf  |  github.com/Lyellr88/marm-memory/discussions"
    )

    try:
        asyncio.run(run_server_with_shutdown())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


def _http_server_is_running() -> bool:
    """Best-effort guard against direct migration beside a live HTTP server."""
    probe_host = SERVER_HOST
    if probe_host in {"0.0.0.0", "::", "[::]"}:
        probe_host = "127.0.0.1"
    request = urllib.request.Request(
        f"http://{probe_host}:{SERVER_PORT}/health", method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=0.75):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
