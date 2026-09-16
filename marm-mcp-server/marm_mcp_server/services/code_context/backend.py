"""In-process access to the graph and memory for the code-context pipeline.

This is the seam that made the feature portable. Outside the server the same
pipeline reached these over HTTP, which meant a second process, a second install
and a localhost round trip per step -- and a `code_context` call makes several.
In-process the whole transport layer disappears and the handlers the Console
already uses are called directly.

The surface is deliberately the six operations `compose` needs and nothing more.
Keeping it that narrow is what lets the pipeline be tested against a stub with
no server at all, which is how its own suite runs.
"""

from typing import Any, Optional

from ...core import code_project_bindings
from ...core.graph_supervisor import graph_supervisor


class GraphUnavailable(RuntimeError):
    """The code graph is not running. Distinct from 'no results'."""


class LocalBackend:
    """Reads the graph and memory in-process, no HTTP."""

    def _client(self) -> Any:
        client = graph_supervisor.get_client()
        if client is None:
            raise GraphUnavailable("code graph backend unavailable")
        return client

    # --- graph ---------------------------------------------------------
    def projects(self) -> list[dict]:
        from marm_graph.core import tool_router as R
        from marm_graph.core.models import GraphIndexRequest

        out = R.do_index(self._client(), GraphIndexRequest(action="list"))
        if isinstance(out, dict) and out.get("status") == "error":
            raise GraphUnavailable(out.get("message", "graph backend unavailable"))
        return (out or {}).get("projects", []) or []

    def search(
        self,
        project: str,
        query: str,
        *,
        limit: int = 25,
        semantic: Optional[str] = None,
    ) -> list[dict]:
        from marm_graph.core import tool_router as R
        from marm_graph.core.models import CodeLookupRequest

        req = CodeLookupRequest(
            project=project, query=query, kind="symbol", limit=limit
        )
        out = R.do_lookup(self._client(), req)
        return (out or {}).get("results", []) or []

    def trace(
        self, project: str, symbol: str, *, depth: int = 2, direction: str = "both"
    ) -> dict:
        from marm_graph.core import tool_router as R
        from marm_graph.core.models import GraphTraceRequest

        req = GraphTraceRequest(
            project=project, function_name=symbol, direction=direction, depth=depth
        )
        return R.do_trace(self._client(), req) or {}

    # --- memory --------------------------------------------------------
    def binding(self, project: str) -> Optional[dict]:
        """The memory scope bound to this code graph, if any.

        Resolved through the binding rather than assumed equal to the graph id:
        they are separate namespaces, and conflating them is what puts a path
        slug where a project name belongs.
        """
        found = code_project_bindings.get_by_graph_project(project)
        if found is None:
            return None
        return {
            "graph_project": found.graph_project,
            "memory_project": found.memory_project,
            "root_path": found.root_path,
        }

    async def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        project: Optional[str] = None,
        search_all: bool = True,
    ) -> list[dict]:
        """Recall memories.

        `search_all` is always on and `project` narrows within it. They are not
        alternatives: `project` is a FILTER over the searched set, so sending it
        alone leaves the search scoped to the default session and every query
        returns no results.
        """
        from ..recall import smart_recall

        out = await smart_recall(
            query, limit=limit, search_all=search_all, project=project
        )
        return (out or {}).get("results", []) or []

    def memory_links(self, project: str) -> list[dict]:
        """Memory→code links recorded for this project's symbols.

        Mirrors : a missing concept database is
        "no links", not an error, because the graph is useful long before
        anything has been linked to it.
        """
        import os

        from ...core.concept_db import ConceptDB, get_concept_db_path

        db_path = get_concept_db_path()
        if not os.path.exists(db_path):
            return []
        try:
            return ConceptDB(db_path).code_links_for_graph_project(project) or []
        except Exception:
            return []
