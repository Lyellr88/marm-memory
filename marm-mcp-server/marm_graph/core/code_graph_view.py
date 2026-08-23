"""Fixed graph queries for the Console, kept off the agent tool surface.

The Architecture tab's table read `modules`, then `module_summary`. No engine
version has ever returned either, so it showed "No module summary available." on
fully indexed projects for the life of the tab. Mapping the engine's `packages`
aspect onto it was tried and reverted: that aspect returns Python builtins and
dependency names with `fan_in` and `fan_out` zero on every row.

So this asks the graph directly. Everything here is a Console view, which is why
it is not in tool_router: that module is shared with the agent tool surface and
its response shapes are asserted by tests.

Three findings from the Phase 1 contract probe are load-bearing, and none of them
are obvious from reading a query:

`query_graph` silently degrades a query it only partly understands. A subscripted
function call, a comma-joined MATCH, or a list comprehension each come back as a
name/qualified_name/label projection of raw nodes, aggregation dropped, with no
error and well-formed JSON. So every reply is checked against the aliases its
query asked for, and a mismatch raises rather than being read as data.

`IMPORTS` has four target labels, not one. `File -> Module` is 377 of 984 edges
on MARM; Function, Variable and Class carry the rest. Aggregating the obvious pair
silently loses 62% of the graph.

Edges are import statements, not dependencies. `from x import a, b` is two edges,
and on MARM raw counts invert the ranking against distinct importers. Coupling is
counted as DISTINCT files, which makes fan-in a lower bound rather than exact:
`from package import module` attributes to a Folder node for the directory and
never to the imported file, so a repo written that way under-reports.

Reference: docs/current/indexing/console-code-units.md
"""

from __future__ import annotations

import re
from typing import Any, Optional

import structlog

from .cbm_client import CbmClient, CbmError, CbmToolError

logger = structlog.get_logger(__name__)

# Every graph read stays bounded independently of the Console response limit.
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
GRAPH_NODE_LIMIT = 80
GRAPH_EDGE_LIMIT = 1_000
NEIGHBORHOOD_EDGE_LIMIT = 200

# Non-code the File label also covers: README.md, pyproject.toml, every yaml in
# the tree. Excluding these is what separates a code structure from a file list.
#
# Deliberately a denylist. An allowlist of code extensions has to keep pace with
# an engine that parses 158 languages, and anything it misses is reported as "no
# source files found" on a project full of source. The first draft was an
# allowlist and it dropped .ps1 from MARM's own tree. Getting this wrong should
# mean an odd row appears, never that real code silently vanishes.
NON_CODE_SUFFIXES = (
    ".md",
    ".markdown",
    ".rst",
    ".txt",
    ".json",
    ".jsonc",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".csv",
    ".tsv",
    ".lock",
    ".log",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
)

# The project is passed as its own tool argument and is never interpolated into a
# query, so nothing from a caller reaches the query text. This validates the
# argument itself against the shape the engine generates, a mangled absolute path.
_PROJECT_RE = re.compile(r"^[A-Za-z0-9._\-]{1,512}$")
_FILE_PATH_RE = re.compile(r"^[A-Za-z0-9._/@+()\[\] -]{1,1024}$")


class CodeGraphViewError(RuntimeError):
    """The graph answered, but not with what was asked for."""


# Constant templates with no interpolation at all. Scoping is the tool's own
# `project` argument, which is what actually restricts the result set.
#
# Do not add `WHERE f.project = ...`. The property exists and is an empty string
# on every node, so that clause matches nothing and returns a well-formed empty
# result with the requested columns intact. The alias guard below cannot catch it,
# and the table reads as `empty_index` on a fully indexed project, which is the
# same silent-wrong-answer this whole view was written to stop.
_UNITS_QUERY = (
    f"MATCH (f:File) RETURN f.file_path AS unit ORDER BY f.file_path LIMIT {MAX_LIMIT}"
)
_FAN_IN_QUERY = (
    "MATCH (a)-[r:IMPORTS]->(b) "
    "RETURN b.file_path AS unit, count(DISTINCT a.file_path) AS fan_in "
    f"ORDER BY fan_in DESC, unit LIMIT {MAX_LIMIT}"
)
_FAN_OUT_QUERY = (
    "MATCH (a)-[r:IMPORTS]->(b) "
    "RETURN a.file_path AS unit, count(DISTINCT b.file_path) AS fan_out "
    f"ORDER BY fan_out DESC, unit LIMIT {MAX_LIMIT}"
)
_IMPORT_EDGE_TOTAL_QUERY = "MATCH (a:File)-[r:IMPORTS]->(b) RETURN count(r) AS total"


def _aliases(query: str) -> list[str]:
    """The aliases a fixed template's RETURN clause asked for, in order."""
    tail = query.split(" RETURN ", 1)[1]
    tail = tail.split(" ORDER BY ", 1)[0]
    return [part.strip().rsplit(" AS ", 1)[-1].strip() for part in tail.split(",")]


def _query(
    client: CbmClient,
    query: str,
    project: str,
    *,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    """Run one fixed template and flatten it, or raise.

    The alias check is the whole reason this wrapper exists. `query_graph` reports
    success for a query it only partly parsed, so comparing the reply's `columns`
    against the aliases requested is the only signal that the answer is the one
    asked for.
    """
    arguments: dict[str, Any] = {"project": project, "query": query, "format": "json"}
    if max_rows is not None:
        arguments["max_rows"] = max_rows
    reply = client.call_tool("query_graph", arguments)
    if not isinstance(reply, dict):
        raise CodeGraphViewError(f"query_graph returned {type(reply).__name__}")

    columns = reply.get("columns")
    if not isinstance(columns, list):
        raise CodeGraphViewError("query_graph reply carried no columns")

    asked = _aliases(query)
    if columns != asked:
        # Degradation, not an empty result. Reading these rows as data is how a
        # 4,000-row node dump becomes a code-units table.
        logger.warning(
            "code_graph_view.degraded", asked=asked, got=columns, query=query
        )
        raise CodeGraphViewError(
            f"query_graph did not run the query as written: asked {asked}, got {columns}"
        )

    rows = reply.get("rows")
    if not isinstance(rows, list):
        return []
    return [dict(zip(columns, row)) for row in rows if isinstance(row, list)]


def _as_int(value: object) -> int:
    """Row values arrive as strings, including the counts."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _import_edges_query(paths: list[str]) -> str:
    """Return the fixed edge template narrowed to the visible file identities."""
    if not paths or not all(_FILE_PATH_RE.fullmatch(path) for path in paths):
        raise ValueError("import edge paths must be validated file identities")
    literals = ", ".join(f"'{path}'" for path in paths)
    return (
        "MATCH (a:File)-[r:IMPORTS]->(b) "
        f"WHERE a.file_path IN [{literals}] AND b.file_path IN [{literals}] "
        "RETURN a.file_path AS source, b.file_path AS target, count(r) AS import_count "
        f"ORDER BY a.file_path, b.file_path LIMIT {GRAPH_EDGE_LIMIT}"
    )


def is_code_unit(path: str) -> bool:
    return not path.lower().endswith(NON_CODE_SUFFIXES)


def unavailable(reason: str, message: str | None = None) -> dict:
    """The `unavailable` state in the shape the browser already renders.

    Every path that cannot produce a table returns this, including the one where
    the graph backend never started. Returning a bare `{"status": "error"}` there
    instead makes the Console adapter raise 503, the query fail, and the table
    render blank, which is the ambiguous empty this whole view exists to end.
    """
    body = {
        "state": "unavailable",
        "reason": reason,
        "total": 0,
        "shown": 0,
        "code_units": [],
    }
    if message:
        body["message"] = message
    return body


def graph_unavailable(reason: str, message: str | None = None) -> dict:
    body = {
        "state": "unavailable",
        "reason": reason,
        "total": {"code_units": 0, "import_edges": 0},
        "rendered": {"code_units": 0, "import_edges": 0},
        "truncated": False,
        "nodes": [],
        "edges": [],
    }
    if message:
        body["message"] = message
    return body


def code_units(
    client: CbmClient,
    project: Optional[str],
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Bounded candidates in the graph with their import coupling, strongest first.

    Returns one of four states so an empty table is never ambiguous:
    `ready`, `indexed_no_summary`, `empty_index`, `unavailable`.
    """
    if not project or not _PROJECT_RE.match(project):
        return unavailable("invalid_project")

    bounded = max(1, min(int(limit), MAX_LIMIT))

    try:
        units = _query(client, _UNITS_QUERY, project)
        fan_in = _query(client, _FAN_IN_QUERY, project)
        fan_out = _query(client, _FAN_OUT_QUERY, project)
    except CodeGraphViewError as exc:
        logger.warning("code_graph_view.contract", project=project, error=str(exc))
        return unavailable("contract_mismatch", str(exc))
    except (CbmToolError, CbmError) as exc:
        # A dead child or an upstream tool error is a Console state, not a 500.
        # call_tool documents both, and tool_router wraps them for every other
        # caller through its own decorator, which this module does not use.
        logger.warning("code_graph_view.backend", project=project, error=str(exc))
        return unavailable("graph_unavailable", str(exc))

    inbound = {str(r.get("unit")): _as_int(r.get("fan_in")) for r in fan_in}
    outbound = {str(r.get("unit")): _as_int(r.get("fan_out")) for r in fan_out}
    paths: list[str] = []
    seen: set[str] = set()

    def add_path(value: object) -> None:
        path = str(value or "")
        if path and path not in seen and is_code_unit(path):
            paths.append(path)
            seen.add(path)

    # These are already ranked by the engine. They must seed the candidate set;
    # an alphabetical File page cannot decide which code belongs in a graph view.
    for result in (fan_in, fan_out):
        for row in result:
            add_path(row.get("unit"))

    # Files without imports never occur in either fan query. Include a bounded
    # alphabetical tail solely for those isolated entry points and leaves.
    for row in units:
        path = str(row.get("unit") or "")
        if len(paths) >= MAX_LIMIT:
            break
        if inbound.get(path, 0) == 0 and outbound.get(path, 0) == 0:
            add_path(path)

    if not paths:
        # Nothing indexed at all reads differently from indexed-but-no-code, and
        # the caller has to be able to tell the user which one happened.
        state = "empty_index" if not units else "indexed_no_summary"
        return {
            "state": state,
            "total": 0,
            "shown": 0,
            "code_units": [],
        }

    # Ranked as typed tuples before becoming dicts: sorting on dict values leaves
    # the counts inferred as object, which the sort key cannot add.
    ranked: list[tuple[str, int, int]] = sorted(
        ((path, inbound.get(path, 0), outbound.get(path, 0)) for path in paths),
        # Coupling first, then path, so two identical requests order identically.
        key=lambda row: (-(row[1] + row[2]), row[0]),
    )
    rows = [
        {"unit": path, "fan_in": fin, "fan_out": fout} for path, fin, fout in ranked
    ]
    sampled = len(rows) > MAX_LIMIT or any(
        len(result) == MAX_LIMIT for result in (units, fan_in, fan_out)
    )
    rows = rows[:MAX_LIMIT]

    return {
        "state": "ready",
        "total": len(rows),
        "shown": min(bounded, len(rows)),
        "sampled": sampled,
        "fan_in_is_lower_bound": True,
        "code_units": rows[:bounded],
    }


def code_graph(client: CbmClient, project: Optional[str]) -> dict:
    """Return a bounded file/import snapshot for the Console canvas.

    The engine's stable, proven projection is a File node plus IMPORTS edges.
    It is deliberately not presented as every raw graph node: symbol-level
    topology needs its own query contract before it can safely be rendered.
    """
    units = code_units(client, project, limit=MAX_LIMIT)
    state = units["state"]
    if state != "ready":
        if state == "unavailable":
            return graph_unavailable(
                str(units.get("reason") or "graph_unavailable"),
                units.get("message"),
            )
        return {
            "state": state,
            "reason": units.get("reason"),
            "message": units.get("message"),
            "total": {"code_units": units["total"], "import_edges": 0},
            "rendered": {"code_units": 0, "import_edges": 0},
            "truncated": False,
            "nodes": [],
            "edges": [],
        }

    visible_units = units["code_units"][:GRAPH_NODE_LIMIT]
    visible_paths = {row["unit"] for row in visible_units}

    assert project is not None
    edge_paths = sorted(path for path in visible_paths if _FILE_PATH_RE.fullmatch(path))
    try:
        edge_rows = (
            _query(client, _import_edges_query(edge_paths), project)
            if edge_paths
            else []
        )
        total_rows = _query(client, _IMPORT_EDGE_TOTAL_QUERY, project)
    except CodeGraphViewError as exc:
        return graph_unavailable("contract_mismatch", str(exc))
    except (CbmToolError, CbmError) as exc:
        return graph_unavailable("graph_unavailable", str(exc))

    total_import_edges = _as_int(total_rows[0].get("total")) if total_rows else 0
    nodes = [
        {
            "id": row["unit"],
            "label": row["unit"].rsplit("/", 1)[-1],
            "path": row["unit"],
            "kind": "file",
            "fan_in": row["fan_in"],
            "fan_out": row["fan_out"],
        }
        for row in visible_units
    ]
    counts: dict[tuple[str, str], int] = {}
    for row in edge_rows:
        source, target = str(row.get("source") or ""), str(row.get("target") or "")
        if source in visible_paths and target in visible_paths and source != target:
            key = (source, target)
            counts[key] = counts.get(key, 0) + _as_int(row.get("import_count"))
    edges = [
        {"source": source, "target": target, "relation": "imports", "count": count}
        for (source, target), count in sorted(counts.items())
    ]
    return {
        "state": "ready",
        "total": {"code_units": units["total"], "import_edges": total_import_edges},
        "rendered": {"code_units": len(nodes), "import_edges": len(edges)},
        "truncated": units["total"] > len(nodes) or total_import_edges > len(edges),
        "sampled": bool(units.get("sampled")),
        "sample_reason": (
            "The canvas shows the most connected code files and their visible import pairs. "
            "The total counts import statements, including repeated pairs."
        ),
        "nodes": nodes,
        "edges": edges,
    }


def code_graph_neighborhood(
    client: CbmClient, project: Optional[str], node_id: str
) -> dict:
    """Return the bounded import neighborhood for one file path.

    The only dynamic fragment is a strictly validated file path inside a
    server-owned equality template. Browser input can select a stable graph
    identity, but cannot alter labels, clauses, or the query's row budget.
    """
    if not project or not _PROJECT_RE.match(project):
        return {
            "state": "unavailable",
            "reason": "invalid_project",
            "nodes": [],
            "edges": [],
        }
    if not _FILE_PATH_RE.match(node_id):
        return {
            "state": "unavailable",
            "reason": "invalid_node",
            "nodes": [],
            "edges": [],
        }

    literal = f"'{node_id}'"
    outbound_query = (
        "MATCH (a:File)-[r:IMPORTS]->(b) "
        f"WHERE a.file_path = {literal} "
        "RETURN a.file_path AS source, b.file_path AS target ORDER BY b.file_path"
    )
    inbound_query = (
        "MATCH (a:File)-[r:IMPORTS]->(b) "
        f"WHERE b.file_path = {literal} "
        "RETURN a.file_path AS source, b.file_path AS target ORDER BY a.file_path"
    )
    outbound_total_query = (
        "MATCH (a:File)-[r:IMPORTS]->(b) "
        f"WHERE a.file_path = {literal} RETURN count(r) AS total"
    )
    inbound_total_query = (
        "MATCH (a:File)-[r:IMPORTS]->(b) "
        f"WHERE b.file_path = {literal} RETURN count(r) AS total"
    )
    try:
        outbound = _query(
            client, outbound_query, project, max_rows=NEIGHBORHOOD_EDGE_LIMIT
        )
        inbound = _query(
            client, inbound_query, project, max_rows=NEIGHBORHOOD_EDGE_LIMIT
        )
        outbound_total = _query(client, outbound_total_query, project)
        inbound_total = _query(client, inbound_total_query, project)
    except CodeGraphViewError as exc:
        return {
            "state": "unavailable",
            "reason": "contract_mismatch",
            "message": str(exc),
            "nodes": [],
            "edges": [],
        }
    except (CbmToolError, CbmError) as exc:
        return {
            "state": "unavailable",
            "reason": "graph_unavailable",
            "message": str(exc),
            "nodes": [],
            "edges": [],
        }

    counts: dict[tuple[str, str], int] = {}
    for row in [*outbound, *inbound]:
        source, target = str(row.get("source") or ""), str(row.get("target") or "")
        if source and target and source != target:
            key = (source, target)
            counts[key] = counts.get(key, 0) + 1
    paths = {node_id}
    for source, target in counts:
        paths.update((source, target))
    rendered_imports = sum(counts.values())
    total_imports = _as_int(outbound_total[0].get("total")) if outbound_total else 0
    total_imports += _as_int(inbound_total[0].get("total")) if inbound_total else 0
    return {
        "state": "ready",
        "seed_id": node_id,
        "total_imports": total_imports,
        "rendered_imports": rendered_imports,
        "truncated": total_imports > rendered_imports,
        "nodes": [
            {
                "id": path,
                "label": path.rsplit("/", 1)[-1],
                "path": path,
                "kind": "file",
                "fan_in": None,
                "fan_out": None,
            }
            for path in sorted(paths)
        ],
        "edges": [
            {"source": source, "target": target, "relation": "imports", "count": count}
            for (source, target), count in sorted(counts.items())
        ],
    }
