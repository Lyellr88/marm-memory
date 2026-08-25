import re
from typing import Any, Optional

from marm_graph.core import tool_router as R
from marm_graph.core.models import CodeLookupRequest

from .graph_supervisor import graph_supervisor


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
                query=f"^{re.escape(entity_name)}$",
                project=project,
                kind="symbol",
                limit=200,
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

    results = result.get("results")
    if not isinstance(results, list):
        return {"status": "unavailable"}
    matches: dict[str, dict[str, Any]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        qualified_name = row.get("qualified_name")
        if not isinstance(qualified_name, str) or not qualified_name:
            continue
        short_name = qualified_name.rsplit(".", 1)[-1]
        if row.get("name") == entity_name or short_name == entity_name:
            matches[qualified_name] = {
                "qualified_name": qualified_name,
                "label": row.get("label"),
                "file_path": row.get("file_path"),
            }
    if not matches:
        return {"status": "no_match"}
    if result.get("has_more") is True or len(matches) != 1:
        return {
            "status": "ambiguous",
            "candidates": sorted(matches),
        }
    match = next(iter(matches.values()))
    return {"status": "matched", **match}
