"""Concept graph's link into marm-graph's code-structure graph.

Originally spec'd as an HTTP client (MARM_GRAPH_URL, port 8003) calling a
separate marm-graph service. By implementation time marm-graph was no longer
a separate service either — PR #78 folded it in-process via
core/graph_supervisor.py + marm_graph.core.tool_router, the same mechanism
endpoints/graph.py already uses for marm_code_lookup. This calls that same
in-process path instead of building an HTTP client. Resolution stays fail-open:
an unavailable graph is explicit evidence the caller must preserve, never an exception.
"""

from typing import Any, Optional

from marm_graph.core import tool_router as R
from marm_graph.core.models import CodeLookupRequest

from .graph_supervisor import graph_supervisor


def is_graph_available() -> bool:
    return graph_supervisor.is_available()


def indexed_project_names() -> set[str]:
    """Return the graph-project names available for exact code linking."""
    if not graph_supervisor.is_available():
        return set()

    client = graph_supervisor.get_client()
    if client is None:
        return set()

    try:
        projects = client.call_tool("list_projects", {}).get("projects", [])
    except Exception:
        return set()
    return {
        project["name"]
        for project in projects
        if isinstance(project, dict) and isinstance(project.get("name"), str)
    }


def find_code_match(entity_name: str, project: Optional[str]) -> dict[str, Any]:
    """Return an explicit exact-symbol resolution outcome without guessing."""
    if not graph_supervisor.is_available():
        return {"status": "unavailable"}

    client = graph_supervisor.get_client()
    if client is None:
        return {"status": "unavailable"}

    try:
        result = R.do_lookup(
            client,
            CodeLookupRequest(
                # symbol kind is BM25 discovery (tool_router.py's search_graph
                # branch), not an exact-name lookup -- limit=1 would truncate
                # to the top-ranked row before the exact-match filter below
                # ever runs, dropping real matches that BM25 didn't rank
                # first. Widen the candidate window, filter for exact match
                # across all of them.
                query=entity_name,
                project=project,
                kind="symbol",
                limit=10,
            ),
        )
    except Exception:
        return {"status": "unavailable"}

    if not isinstance(result, dict) or result.get("status") in (
        "no_project",
        "ambiguous_project",
        "error",
    ):
        return {"status": "unavailable"}

    results = result.get("results") or []
    matches: dict[str, dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        qualified_name = row.get("qualified_name")
        if not isinstance(qualified_name, str) or not qualified_name:
            continue
        # "name" isn't guaranteed on every row shape returned by search_graph,
        # so also accept an exact match against qualified_name's last segment
        # (e.g. "module.Class.method" -> "method").
        short_name = qualified_name.rsplit(".", 1)[-1]
        if row.get("name") == entity_name or short_name == entity_name:
            matches[qualified_name] = {
                "qualified_name": qualified_name,
                "label": row.get("label"),
                "file_path": row.get("file_path"),
            }
    if not matches:
        return {"status": "no_match"}
    if len(matches) != 1:
        return {
            "status": "ambiguous",
            "candidates": sorted(matches),
        }
    match = next(iter(matches.values()))
    return {"status": "matched", **match}
