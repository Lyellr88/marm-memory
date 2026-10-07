from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from marm_graph.core.cbm_client import CbmClient

import structlog

from marm_graph.core import tool_router as R
from marm_graph.core.models import GraphIndexRequest

from . import code_link_queue, code_project_bindings, runtime_flags

logger = structlog.get_logger(__name__)


def _invalidate_code_context_projects() -> None:
    """Drop the code-context project cache, tolerating its absence.

    Imported lazily and guarded: this worker must not fail an index because an
    optional consumer of the project list could not be imported.
    """
    try:
        from ..services.code_context.backend import invalidate_projects_cache

        invalidate_projects_cache()
    except Exception:  # pragma: no cover - defensive
        pass


def index_repository(client: "CbmClient", req: GraphIndexRequest) -> dict:
    """The callable every index path hands to the gate: index, then settle the
    durable block state before the lease is released.

    Settling it afterwards left the two blocks racing each other, because both
    transports index concurrently by design. An automatic index that fails on the
    path limit and a manual one that succeeds could release their gates in either
    order, and the loser's write won: a recovered repository stayed marked
    unindexable, silently, in both processes.

    One function rather than a rule at four call sites, because the rule is
    invisible at the call site and there is nothing to notice when it is skipped.
    """
    snapshot_at = datetime.now(timezone.utc).isoformat()
    result: dict = R.do_index(client, req)
    # The set of indexed projects may have just changed, and code-context caches
    # it. Invalidated here rather than at each caller for the reason above: a
    # rule at four call sites is invisible when it is skipped.
    _invalidate_code_context_projects()
    root = req.repo_path
    if not root:
        return result
    if result.get("status") == "error":
        if result.get("error_code") == "windows_path_too_long":
            runtime_flags.mark_unindexable(root, "windows_path_too_long")
        return result
    runtime_flags.clear_index_blocks(root)
    graph_project = result.get("project")
    if isinstance(graph_project, str) and graph_project:
        try:
            binding_state, binding = code_project_bindings.auto_bind(
                graph_project, root
            )
            result["memory_linking"] = {"state": binding_state}
            if binding is not None:
                code_link_queue.enqueue_refresh(
                    binding.graph_project,
                    binding.memory_project,
                    binding.root_path,
                    snapshot_at=snapshot_at,
                )
                result["memory_linking"]["memory_project"] = binding.memory_project
                result["memory_linking"]["refresh_queued"] = True
        except Exception as exc:
            logger.warning("code_linking.enqueue_failed", error=str(exc))
    return result
