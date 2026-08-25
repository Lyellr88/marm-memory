import os

import structlog

from ..config import settings
from .cbm_client import CbmClient

logger = structlog.get_logger(__name__)

AI_OPERATIONS = [
    "marm_graph_index",
    "marm_code_lookup",
    "marm_graph_trace",
    "marm_graph_architecture",
    "marm_graph_impact",
]

_EXPECTED_UPSTREAM_TOOLS = {
    "index_repository",
    "search_graph",
    "query_graph",
    "trace_path",
    "get_code_snippet",
    "get_graph_schema",
    "get_architecture",
    "search_code",
    "list_projects",
    "delete_project",
    "index_status",
    "detect_changes",
    "manage_adr",
    "ingest_traces",
}

_KNOWN_EXTRA_UPSTREAM_TOOLS = {
    "check_index_coverage",
}


def verify_and_start(client: CbmClient) -> None:
    """Start the child, verify the binary trust boundary, check for schema drift."""
    if settings.CBM_BINARY_PATH and not os.path.exists(settings.CBM_BINARY_PATH):
        raise RuntimeError(
            f"CBM_BINARY_PATH does not exist: {settings.CBM_BINARY_PATH}"
        )
    settings.STORE_DIR.mkdir(parents=True, exist_ok=True)
    client.start()
    logger.info(
        "cbm.backend_ready",
        spawn_command=settings.cbm_spawn_command(),
        pinned_pip_version=settings.PINNED_CBM_VERSION,
        binary_version=client.server_version,
    )
    try:
        names = {t["name"] for t in client.list_tools()}
    except Exception as e:
        raise RuntimeError(
            f"Could not list upstream tools to verify schema: {e}"
        ) from e
    check_schema(names)


def check_schema(names: set[str]) -> None:
    """Fail fast if an expected upstream tool is gone; warn on unexpected extras.

    tools/list is a fixed contract that tool_router maps by hand. A missing tool
    means a hand-written mapping is silently broken, so refuse to start. Extra
    tools are forward-compatible and only worth a warning.
    """
    missing = _EXPECTED_UPSTREAM_TOOLS - names
    extra = names - _EXPECTED_UPSTREAM_TOOLS - _KNOWN_EXTRA_UPSTREAM_TOOLS
    if missing:
        raise RuntimeError(
            f"Upstream schema drift: expected codebase-memory-mcp tools missing "
            f"from the binary: {sorted(missing)}. The pinned contract changed, "
            f"so review the router mapping before running."
        )
    if extra:
        logger.warning("cbm.schema_drift_extra", extra=sorted(extra))
    else:
        logger.info("cbm.schema_ok", tool_count=len(names))
