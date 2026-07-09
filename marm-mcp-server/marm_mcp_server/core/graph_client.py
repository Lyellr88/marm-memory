"""Concept graph's link into marm-graph's code-structure graph.

Originally spec'd as an HTTP client (MARM_GRAPH_URL, port 8003) calling a
separate marm-graph service. By implementation time marm-graph was no longer
a separate service either — PR #78 folded it in-process via
core/graph_supervisor.py + marm_graph.core.tool_router, the same mechanism
endpoints/graph.py already uses for marm_code_lookup. This calls that same
in-process path instead of building an HTTP client. Soft-fail behavior is
unchanged: marm-graph unavailable/not indexed -> no match, no exception.
"""

from typing import Optional

from marm_graph.core import tool_router as R
from marm_graph.core.models import CodeLookupRequest

from .graph_supervisor import graph_supervisor


def is_graph_available() -> bool:
    return graph_supervisor.is_available()


def find_code_match(entity_name: str, project: Optional[str]) -> Optional[dict]:
    """Exact-match lookup of an entity name against marm-graph's indexed
    symbols. Returns {qualified_name, label, file_path} on a match, None on
    no match, no client, no indexed project, or any error — never raises."""
    if not graph_supervisor.is_available():
        return None

    client = graph_supervisor.get_client()
    if client is None:
        return None

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
        return None

    if not isinstance(result, dict) or result.get("status") in (
        "no_project",
        "ambiguous_project",
        "error",
    ):
        return None

    results = result.get("results") or []
    for row in results:
        qualified_name = row.get("qualified_name")
        if not qualified_name:
            continue
        # "name" isn't guaranteed on every row shape returned by search_graph,
        # so also accept an exact match against qualified_name's last segment
        # (e.g. "module.Class.method" -> "method").
        short_name = qualified_name.rsplit(".", 1)[-1]
        if row.get("name") == entity_name or short_name == entity_name:
            return {
                "qualified_name": qualified_name,
                "label": row.get("label"),
                "file_path": row.get("file_path"),
            }

    return None
