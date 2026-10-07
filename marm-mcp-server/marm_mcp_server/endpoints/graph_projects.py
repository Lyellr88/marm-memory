import os

from marm_graph.core import tool_router as R
from marm_graph.core.cbm_client import CbmError
from marm_graph.core.models import GraphIndexRequest

from ..core import code_link_queue, code_project_bindings, runtime_flags
from ..core.concept_db import ConceptDB, get_concept_db_path
from ..core.graph_supervisor import graph_supervisor
from ..services.code_context.backend import invalidate_projects_cache

_UNAVAILABLE = {"status": "error", "message": "graph backend unavailable"}


def _project_root_path(project: str) -> str | None:
    client = graph_supervisor.get_client()
    if client is None:
        return None
    result = R.do_index(client, GraphIndexRequest(action="list"))
    if result.get("status") == "error":
        return None
    for entry in result.get("projects", []):
        if (entry or {}).get("name") == project:
            return (entry or {}).get("root_path")
    return None


def _resolve_and_delete(project: str) -> tuple[str | None, str | None, dict]:
    """Resolve the root, delete the project, write its tombstone. Under the gate.

    The root has to be read before the delete, because afterwards the project is
    gone and its root path with it, and without the path there is nothing to
    suppress: the poller would re-index the root from its cached watch set and
    recreate what the user just deleted.

    The tombstone is written here rather than by the caller for the same reason
    the delete itself is gated. Writing it after the gate was released left a
    window where the other transport's poller could take the gate and start an
    opaque re-index of its cached root; a tombstone written after that call is
    already running cannot stop it, and the project comes back.
    """
    client = graph_supervisor.get_client()
    if client is None:
        return None, None, dict(_UNAVAILABLE)
    root_path = _project_root_path(project)
    try:
        result = client.call_tool("delete_project", {"project": project})
    except CbmError as exc:
        return None, None, {"status": "error", "message": f"delete failed: {exc}"}
    failed = isinstance(result, dict) and result.get("status") == "error"
    if failed:
        return root_path, None, result
    # Here rather than in the caller, for the same reason the tombstone is:
    # `run_exclusive` awaits a shielded task, so a cancelled request detaches
    # while the delete runs on. Anything after that await is skipped, and the
    # deleted project would stay offered until the cache TTL expired.
    invalidate_projects_cache()
    try:
        _cleanup_project_code_links(project)
    except Exception:
        if isinstance(result, dict):
            result["code_link_cleanup"] = "failed"
    if not root_path:
        return None, "unresolved_root", result
    try:
        runtime_flags.suppress_watch(root_path)
    except Exception:
        return root_path, "failed", result
    return root_path, None, result


def _cleanup_project_code_links(project: str) -> None:
    code_link_queue.drop_project(project)
    code_project_bindings.drop_graph_project(project)
    db_path = get_concept_db_path()
    if os.path.exists(db_path):
        ConceptDB(db_path).cleanup_graph_project_links(project)


def _memory_linking_status(project: str, root_path: str | None) -> dict:
    try:
        binding = code_project_bindings.get_by_graph_project(project)
        queue = code_link_queue.status(project)
    except Exception:
        return {
            "state": "unbound",
            "binding": None,
            "candidates": [],
            "refresh": None,
            "linked_entities": 0,
        }
    linked_entities = 0
    db_path = get_concept_db_path()
    if os.path.exists(db_path):
        try:
            linked_entities = ConceptDB(db_path).graph_project_link_count(project)
        except Exception:
            linked_entities = 0
    if binding is None:
        try:
            candidates = code_project_bindings.matching_memory_project_scopes(
                project, root_path
            )
        except Exception:
            candidates = []
        return {
            "state": "ambiguous" if len(candidates) > 1 else "unbound",
            "binding": None,
            "candidates": candidates,
            "refresh": queue,
            "linked_entities": linked_entities,
        }
    return {
        "state": "bound",
        "binding": binding.as_dict(),
        "candidates": [],
        "refresh": queue,
        "linked_entities": linked_entities,
    }
