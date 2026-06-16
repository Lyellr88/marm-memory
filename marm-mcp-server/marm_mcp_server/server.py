"""
MARM MCP Server - Memory Accurate Response Mode for Model Context Protocol

This server integrates all modular components of the MARM protocol into a single
FastAPI application, compliant with the MCP protocol via FastApiMCP.

Author: Lyell - MARM Systems
Version: 2.13.2
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP

from .config import settings
from .config.settings import (
    ANALYTICS_DB_PATH,
    COMPACTION_AUTO_APPLY_ENABLED,
    COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
    COMPACTION_ENABLED,
    DEFAULT_DB_PATH,
    SCHEDULER_AVAILABLE,
    SEMANTIC_SEARCH_AVAILABLE,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_VERSION,
)
from .core import memory as memory_module
from .core.compaction import claim_pending_compaction_prompt
from .core.memory import memory
from .core.rate_limiter import rate_limiter
from .endpoints.compaction import router as compaction_router
from .endpoints.logging import router as logging_router
from .endpoints.memory import router as memory_router
from .endpoints.notebook import router as notebook_router
from .endpoints.reasoning import router as reasoning_router
from .endpoints.session import router as session_router
from .endpoints.system import router as system_router
from .middleware.auth import auth_middleware
from .middleware.rate_limiting import rate_limit_middleware
from .services.automation import register_event_handlers
from .services.documentation import (
    docs_are_loaded,
    ensure_marm_started,
    maybe_auto_refresh,
)
from .utils.helpers import read_protocol_file, read_protocol_lite_file
from .utils.security import generate_api_key


class _SuppressProactorWindowsNoise(logging.Filter):
    """Suppress benign WinError 10054 noise from ProactorEventLoop disconnect cleanup.

    The asyncio log record has '_ProactorBasePipeTransport' in the message text
    and the actual ConnectionResetError in record.exc_info — not in getMessage().
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if "_ProactorBasePipeTransport" not in record.getMessage():
            return True
        if not record.exc_info:
            return True

        exc = record.exc_info[1]
        if not isinstance(exc, ConnectionResetError):
            return True

        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        return not (winerror == 10054 or errno == 10054)


_proactor_noise_filter = _SuppressProactorWindowsNoise()
logging.getLogger("asyncio").addFilter(_proactor_noise_filter)


logger = structlog.get_logger()


def _detect_requested_worker_count() -> int | None:
    """Best-effort detection for unsupported multi-process HTTP launches."""
    for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        value = os.environ.get(key)
        if value and value.isdigit():
            return int(value)

    gunicorn_args = os.environ.get("GUNICORN_CMD_ARGS", "")
    parts = gunicorn_args.split()
    for index, part in enumerate(parts):
        if part in ("--workers", "-w") and index + 1 < len(parts):
            value = parts[index + 1]
            if value.isdigit():
                return int(value)
        if part.startswith("--workers="):
            value = part.split("=", 1)[1]
            if value.isdigit():
                return int(value)
    return None


def _warn_if_multi_process_requested() -> None:
    workers = _detect_requested_worker_count()
    if workers and workers > 1:
        logger.warning(
            "Unsupported multi-process HTTP deployment requested",
            workers=workers,
            supported_workers=1,
            reason=(
                "MARM coordinates write queue, compaction counters, scheduler, "
                "and protocol delivery in process-local state"
            ),
            recommendation=(
                "Run one MARM process per SQLite database. Use --swarm/--swarm-max "
                "inside a single process for shared HTTP agent load."
            ),
        )


def track_usage(event_type: str, endpoint: str = None, user_data: dict = None):
    """Track MCP usage events for launch analytics"""
    try:
        usage_db = ANALYTICS_DB_PATH

        with sqlite3.connect(usage_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    endpoint TEXT,
                    user_agent TEXT,
                    ip_address TEXT,
                    session_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute(
                """
                INSERT INTO usage_events (timestamp, event_type, endpoint, user_agent, ip_address, session_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    datetime.now().isoformat(),
                    event_type,
                    endpoint,
                    user_data.get("user_agent", "unknown") if user_data else "unknown",
                    user_data.get("ip_address", "unknown") if user_data else "unknown",
                    user_data.get("session_id", "unknown") if user_data else "unknown",
                    str(user_data) if user_data else "{}",
                ),
            )

        logger.info("Usage tracked", event_type=event_type, endpoint=endpoint)
    except Exception as e:
        logger.warning("Analytics tracking failed", error=str(e))


def _maybe_start_compaction_scheduler():
    """Start the compaction maintenance APScheduler job.

    Runs whenever COMPACTION_ENABLED is true — auto-apply is optional on top.
    nudge_exhausted processing always runs so candidates are never permanently dead-ended.
    """
    if not SCHEDULER_AVAILABLE or not COMPACTION_ENABLED:
        return None
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from .services.compaction_summarize import process_nudge_exhausted_candidates

    if COMPACTION_AUTO_APPLY_ENABLED:
        from .endpoints.compaction import auto_apply_staged_summaries

        async def _job():
            await process_nudge_exhausted_candidates(memory)
            await auto_apply_staged_summaries()
    else:

        async def _job():
            await process_nudge_exhausted_candidates(memory)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _job,
        "interval",
        minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        id="compaction_auto_apply",
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Compaction scheduler started",
        interval_minutes=COMPACTION_AUTO_APPLY_INTERVAL_MINUTES,
        auto_apply=COMPACTION_AUTO_APPLY_ENABLED,
    )
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Modern FastAPI lifespan management for startup and shutdown"""
    logger.info("Initializing MARM MCP Server", version=SERVER_VERSION)
    _warn_if_multi_process_requested()

    memory_before = get_memory_usage()
    logger.info("Initial memory usage", memory_mb=f"{memory_before:.1f}")

    logger.info(
        "Database locations", memory_db=DEFAULT_DB_PATH, analytics_db=ANALYTICS_DB_PATH
    )

    register_event_handlers()
    await memory.start_write_queue()
    memory.restore_active_session()

    _compaction_scheduler = _maybe_start_compaction_scheduler()

    memory_after = get_memory_usage()
    logger.info("Memory usage after startup", memory_mb=f"{memory_after:.1f}")

    memory_increase = memory_after - memory_before
    logger.info("Startup memory increase", increase_mb=f"{memory_increase:.1f}")

    logger.info("MARM MCP Server initialization complete")

    track_usage("server_startup", user_data={"version": SERVER_VERSION})

    yield

    logger.info("Shutting down MARM MCP Server")
    if _compaction_scheduler and _compaction_scheduler.running:
        _compaction_scheduler.shutdown(wait=False)
    await memory.stop_write_queue()
    track_usage("server_shutdown")


app = FastAPI(
    title="MARM MCP Server",
    description="Memory Accurate Response Mode - Complete Protocol Implementation",
    version=SERVER_VERSION,
    lifespan=lifespan,
)

_PROTOCOL_DELIVERY_MAX_SESSIONS = 4096
_PROTOCOL_DELIVERY_TTL_SECONDS = 24 * 60 * 60
_protocol_delivered_sessions: OrderedDict[str, float] = OrderedDict()
_protocol_delivery_lock = asyncio.Lock()
_PROTOCOL_LITE_INTERVAL = 30
_protocol_call_counts: dict[str, int] = {}
_PROTOCOL_CALL_COUNTS_MAX_SESSIONS = 4096


def _prune_call_counts() -> None:
    """Prune call counts to match delivered sessions.

    Removes entries for sessions that are no longer in
    _protocol_delivered_sessions (aged out by TTL or max-sessions cap).
    Also enforces hard cap when count grows too large.
    """
    # Prune sessions not in delivered set
    delivered = set(_protocol_delivered_sessions)
    stale = [k for k in _protocol_call_counts if k not in delivered]
    for k in stale:
        _protocol_call_counts.pop(k, None)
    # Hard cap as safety net
    if len(_protocol_call_counts) > _PROTOCOL_CALL_COUNTS_MAX_SESSIONS:
        excess = list(_protocol_call_counts.keys())[
            :-_PROTOCOL_CALL_COUNTS_MAX_SESSIONS
        ]
        for k in excess:
            _protocol_call_counts.pop(k, None)


def _protocol_session_delivered(session_name: str, now: float | None = None) -> bool:
    if not isinstance(_protocol_delivered_sessions, OrderedDict):
        return session_name in _protocol_delivered_sessions
    now = now or time.monotonic()
    _prune_protocol_delivered_sessions(now)
    return session_name in _protocol_delivered_sessions


def _mark_protocol_session_delivered(
    session_name: str, now: float | None = None
) -> None:
    if not isinstance(_protocol_delivered_sessions, OrderedDict):
        _protocol_delivered_sessions.add(session_name)
        return
    now = now or time.monotonic()
    _protocol_delivered_sessions[session_name] = now
    _protocol_delivered_sessions.move_to_end(session_name)
    _prune_protocol_delivered_sessions(now)


def _prune_protocol_delivered_sessions(now: float | None = None) -> None:
    if not isinstance(_protocol_delivered_sessions, OrderedDict):
        return
    now = now or time.monotonic()
    while _protocol_delivered_sessions:
        _, delivered_at = next(iter(_protocol_delivered_sessions.items()))
        if now - delivered_at <= _PROTOCOL_DELIVERY_TTL_SECONDS:
            break
        _protocol_delivered_sessions.popitem(last=False)
    while len(_protocol_delivered_sessions) > _PROTOCOL_DELIVERY_MAX_SESSIONS:
        _protocol_delivered_sessions.popitem(last=False)


async def _mcp_tool_call_tracker(request: Request, call_next):
    """Lazy doc-load and auto-refresh for MCP tool calls.

    Registered first so LIFO puts it last — only runs after rate_limit and auth pass.
    Only acts on tools/call requests; init, discovery, and rejected requests are ignored.
    Doc loading runs before the handler so the first tool call gets warm docs,
    matching STDIO transport timing.

    On the first successful tool call for each session, the MARM protocol is injected
    into the response so each agent receives it exactly once. Tracked per session_name
    in _protocol_delivered_sessions. Tools that omit session_name share a "__default__"
    scope — agents should use distinct session names for independent delivery.
    Note: the session is marked delivered when read_protocol_file() succeeds; a later
    failure during response mutation marks the session delivered even if the client
    did not receive the injection.
    """
    is_tool_call = False
    body = b""
    if request.method == "POST" and request.url.path == "/mcp":
        try:
            body = await request.body()
            is_tool_call = b'"tools/call"' in body
        except Exception as exc:
            logger.debug(
                "Failed to parse MCP tool call body for session routing",
                error=str(exc),
                body_preview=body[:200].decode("utf-8", errors="replace"),
                exc_info=True,
            )

    if is_tool_call and not docs_are_loaded():
        await ensure_marm_started("default")

    response = await call_next(request)

    if is_tool_call:
        asyncio.create_task(maybe_auto_refresh())  # noqa: RUF006

    if is_tool_call and response.status_code == 200:
        _explicit_session = None
        _tool_name = None
        try:
            _parsed_body = json.loads(body)
            _explicit_session = (
                _parsed_body.get("params", {}).get("arguments", {}).get("session_name")
            ) or None
            _tool_name = _parsed_body.get("params", {}).get("name")
        except Exception:
            pass

        _protocol_session = _explicit_session or "__default__"
        if _explicit_session:
            _compaction_session = _explicit_session
        elif _tool_name == "marm_log_entry":
            _compaction_session = memory.active_log_session
        elif _tool_name in ("marm_notebook", "marm_smart_recall"):
            _compaction_session = "main"
        else:
            _compaction_session = None

        # Move counter and pruning under lock to prevent races
        async with _protocol_delivery_lock:
            _protocol_call_counts[_protocol_session] = (
                _protocol_call_counts.get(_protocol_session, 0) + 1
            )
            call_count = _protocol_call_counts[_protocol_session]
            _prune_call_counts()

            # Skip body mutation if protocol already delivered, compaction off,
            # and we're not at the lite reinjection interval.
            if (
                _protocol_session_delivered(_protocol_session)
                and not settings.COMPACTION_ENABLED
            ):
                if call_count % _PROTOCOL_LITE_INTERVAL != 0:
                    return response
                # Fall through to inject lite protocol below.

        try:
            content_type = response.headers.get("content-type", "") or ""
            if (
                isinstance(content_type, str)
                and content_type
                and "application/json" not in content_type
            ):
                return response
        except Exception:
            pass

        body_bytes = b""
        try:
            async for chunk in response.body_iterator:
                body_bytes += chunk
            data = json.loads(body_bytes)
            result = data.get("result", {})
            content = result.get("content")

            if not isinstance(content, list):
                from starlette.responses import Response as StarletteResponse

                return StarletteResponse(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )

            injections = []
            protocol_injected = False
            async with _protocol_delivery_lock:
                if not _protocol_session_delivered(_protocol_session):
                    protocol_content = await read_protocol_file()
                    injections.append(
                        {
                            "type": "text",
                            "text": f"[MARM SESSION INIT]\n\n{protocol_content}",
                        }
                    )
                    _mark_protocol_session_delivered(_protocol_session)
                    protocol_injected = True
                elif call_count % _PROTOCOL_LITE_INTERVAL == 0:
                    lite_content = await read_protocol_lite_file()
                    if lite_content:
                        injections.append(
                            {
                                "type": "text",
                                "text": f"[MARM PROTOCOL REFRESH]\n\n{lite_content}",
                            }
                        )
                        # Lite does not set protocol_injected=True — allows
                        # compaction to coexist on the same call.

            if not protocol_injected:
                compaction_block = await asyncio.to_thread(
                    claim_pending_compaction_prompt, memory, _compaction_session
                )
                if compaction_block:
                    injections.append(compaction_block)

            if not injections:
                from starlette.responses import Response as StarletteResponse

                return StarletteResponse(
                    content=body_bytes,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )

            content[:0] = injections
            return JSONResponse(
                content=data,
                status_code=response.status_code,
                headers={
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in ("content-length", "content-type")
                },
            )
        except Exception as e:
            logger.warning("Protocol injection failed", error=str(e))
            from starlette.responses import Response as StarletteResponse

            return StarletteResponse(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type="application/json",
            )

    return response


app.middleware("http")(_mcp_tool_call_tracker)
app.middleware("http")(auth_middleware)
app.middleware("http")(rate_limit_middleware)


def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024


app.include_router(session_router)
app.include_router(logging_router)
app.include_router(reasoning_router)
app.include_router(notebook_router)
app.include_router(memory_router)
app.include_router(system_router)
app.include_router(compaction_router)


mcp = FastApiMCP(app)
mcp.mount_http()


def check_dependencies():
    """Validate all system dependencies and requirements"""
    print("MARM MCP Server - Dependency Check")
    print("=" * 40)

    issues = []

    python_version = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    print(f"Python version: {python_version}")
    if sys.version_info < (3, 8):
        issues.append("Python 3.8+ required")
    else:
        print("Python version OK")

    required_modules = [
        ("fastapi", "FastAPI web framework"),
        ("fastapi_mcp", "MCP protocol implementation"),
        ("uvicorn", "ASGI web server"),
        ("pydantic", "Data validation"),
        ("sqlite3", "Database (built-in)"),
        ("structlog", "Structured logging"),
    ]

    for module, description in required_modules:
        try:
            __import__(module)
            print(f"OK {description}")
        except ImportError:
            issues.append(f"Missing: {module} ({description})")
            print(f"Missing: {module}")

    print("\nOptional Features:")
    if SEMANTIC_SEARCH_AVAILABLE:
        print("OK Semantic search (sentence-transformers)")
    else:
        print("Semantic search disabled - install sentence-transformers")

    if SCHEDULER_AVAILABLE:
        print("OK Automation scheduler (apscheduler)")
    else:
        print("Scheduler disabled - install apscheduler")

    print(f"\nDatabase location: {DEFAULT_DB_PATH}")
    db_dir = Path(DEFAULT_DB_PATH).parent
    if db_dir.exists() and os.access(db_dir, os.W_OK):
        print("OK Database directory writable")
    else:
        issues.append(f"Cannot write to database directory: {db_dir}")

    print("\n" + "=" * 40)
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"   • {issue}")
        print("\nRun: pip install -r requirements.txt")
        return False
    else:
        print("All dependencies satisfied!")
        print("Ready to start MARM MCP Server")
        return True


async def run_server_with_shutdown():
    """Run server with proper signal handling and graceful shutdown"""
    from .core.shutdown_manager import shutdown_manager

    await shutdown_manager.setup_signal_handlers()

    config = uvicorn.Config(app, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
    server = uvicorn.Server(config)

    server_task = asyncio.create_task(server.serve())

    shutdown_task = asyncio.create_task(shutdown_manager.wait_for_shutdown())

    done, pending = await asyncio.wait(
        [server_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
    )

    if shutdown_task in done:
        logger.info("Shutdown signal received, closing server")

        await shutdown_manager.graceful_shutdown()

        server.should_exit = True

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            await server_task
        except asyncio.CancelledError:
            pass

        logger.info("Server shutdown complete")


def create_server():
    """Return the FastAPI app instance for external use."""
    return app


def apply_runtime_preset(
    *,
    swarm: bool = False,
    swarm_max: bool = False,
    trusted: bool = False,
    rate_limit_rpm: Optional[int] = None,
) -> dict:
    """Apply CLI rate-limit/write-queue presets to already-imported runtime modules."""
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
            "ENABLED"
            if SEMANTIC_SEARCH_AVAILABLE
            else "DISABLED - install sentence-transformers"
        ),
        scheduler=(
            "ENABLED" if SCHEDULER_AVAILABLE else "DISABLED - install apscheduler"
        ),
        rate_limiting=(
            "DISABLED" if runtime_config["rate_limit_rpm"] == 0 else "ENABLED"
        ),
        write_queue="ENABLED" if runtime_config["write_queue_enabled"] else "DISABLED",
    )

    try:
        asyncio.run(run_server_with_shutdown())
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
