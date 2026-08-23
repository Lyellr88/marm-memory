"""Tests for the Console code-units view.

Every payload here is verbatim `query_graph` output from engine 0.10.5, captured
by scripts/benchmarking/accuracy/code-graph/probe_code_units.py. That matters more
than usual: this module exists because the engine answers a partly-understood
query with a well-formed reply that is not the answer, so a fabricated payload
would test the happy path the real engine does not always take.

The degradation shapes are real too. `["labels(n)"]` is what a subscripted
function call returns, and `["f.name", "f.qualified_name", "f.label"]` is what a
comma-joined MATCH returns, both with rows attached and no error anywhere.
"""

import pytest

from marm_graph.core import code_graph_view as V
from marm_graph.core.cbm_client import CbmError, CbmToolError

UNITS_REPLY = {
    "columns": ["unit"],
    "rows": [
        ["README.md"],
        ["marm-mcp-server/marm_mcp_server/config/settings.py"],
        ["marm-mcp-server/marm_mcp_server/core/memory.py"],
        ["marm-mcp-server/marm_mcp_server/server.py"],
        ["pyproject.toml"],
    ],
    "total": 5,
}

FAN_IN_REPLY = {
    "columns": ["unit", "fan_in"],
    "rows": [
        ["marm-mcp-server/marm_mcp_server/config/settings.py", "37"],
        ["marm-mcp-server/marm_mcp_server/core/memory.py", "33"],
    ],
    "total": 2,
}

FAN_OUT_REPLY = {
    "columns": ["unit", "fan_out"],
    "rows": [
        ["marm-mcp-server/marm_mcp_server/config/settings.py", "2"],
        ["marm-mcp-server/marm_mcp_server/core/memory.py", "9"],
        ["marm-mcp-server/marm_mcp_server/server.py", "24"],
    ],
    "total": 3,
}

# Verbatim degraded replies. Well-formed, no error, wrong answer.
DEGRADED_SUBSCRIPT = {
    "columns": ["labels(n)"],
    "rows": [['["Variable"]'], ['["Section"]']],
    "total": 4202,
}
DEGRADED_COMMA_JOIN = {
    "columns": ["f.name", "f.qualified_name", "f.label"],
    "rows": [["settings.py", "proj.settings.__file__", "File"]],
    "total": 278,
}

PROJECT = "C-Users-lyell-Desktop-MARM-Systems"


class FakeClient:
    """Answers by matching the query text, and records the args it was given."""

    def __init__(self, replies: dict | None = None, override: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.override = override or {}
        self.replies = replies or {
            "f.file_path AS unit": UNITS_REPLY,
            "count(DISTINCT a.file_path) AS fan_in": FAN_IN_REPLY,
            "count(DISTINCT b.file_path) AS fan_out": FAN_OUT_REPLY,
        }

    def call_tool(self, name: str, arguments: dict, timeout=None):
        self.calls.append((name, arguments))
        query = arguments.get("query", "")
        for marker, reply in self.override.items():
            if marker in query:
                return reply
        for marker, reply in self.replies.items():
            if marker in query:
                return reply
        raise AssertionError(f"unexpected query: {query}")


def test_units_are_ranked_by_total_coupling_with_a_stable_tie_break():
    result = V.code_units(FakeClient(), PROJECT)

    assert result["state"] == "ready"
    units = [row["unit"] for row in result["code_units"]]
    # memory.py 33+9=42, settings.py 37+2=39, server.py 0+24=24.
    assert units == [
        "marm-mcp-server/marm_mcp_server/core/memory.py",
        "marm-mcp-server/marm_mcp_server/config/settings.py",
        "marm-mcp-server/marm_mcp_server/server.py",
    ]
    assert result["code_units"][0] == {
        "unit": "marm-mcp-server/marm_mcp_server/core/memory.py",
        "fan_in": 33,
        "fan_out": 9,
    }


def test_a_unit_with_no_inbound_edge_reports_zero_rather_than_being_dropped():
    """server.py is an entry point: nothing imports it, and it must still appear.

    Absent from the fan-in reply is not absent from the codebase, and an entry
    point vanishing from a code-structure table is the bug this guards.
    """
    result = V.code_units(FakeClient(), PROJECT)
    server = [
        row
        for row in result["code_units"]
        if row["unit"].endswith("marm_mcp_server/server.py")
    ]
    assert server == [
        {
            "unit": "marm-mcp-server/marm_mcp_server/server.py",
            "fan_in": 0,
            "fan_out": 24,
        }
    ]


def test_non_code_files_are_excluded_from_a_code_structure_table():
    result = V.code_units(FakeClient(), PROJECT)
    units = [row["unit"] for row in result["code_units"]]
    assert "README.md" not in units
    assert "pyproject.toml" not in units
    assert result["total"] == 3


def test_every_call_asks_for_json_checked_on_the_arguments_not_the_reply():
    """The prose default silently flattened five router calls and a benchmark.

    Asserted on what was sent, because a fake reply is JSON either way and would
    pass this test whether or not the argument was set.
    """
    client = FakeClient()
    V.code_units(client, PROJECT)

    assert client.calls, "no query was issued"
    for name, args in client.calls:
        assert name == "query_graph"
        assert args["format"] == "json"
        assert args["project"] == PROJECT


def test_the_project_never_reaches_the_query_string():
    """A WHERE on f.project also returns empty on a full index, so this guards
    correctness as well as the injection boundary."""
    client = FakeClient()
    V.code_units(client, "'; MATCH (n) DETACH DELETE n; --")

    # Refused before any call is made.
    assert client.calls == []


def test_an_invalid_project_is_unavailable_rather_than_empty():
    result = V.code_units(FakeClient(), "has spaces and quotes '")
    assert result["state"] == "unavailable"
    assert result["reason"] == "invalid_project"
    assert result["code_units"] == []


@pytest.mark.parametrize(
    "degraded",
    [DEGRADED_SUBSCRIPT, DEGRADED_COMMA_JOIN],
    ids=["subscripted_call", "comma_joined_match"],
)
def test_a_degraded_reply_is_refused_instead_of_read_as_data(degraded):
    """The whole reason this module wraps query_graph.

    A degraded reply carries rows and no error. Read as data it becomes a table
    of node names; refused it becomes an honest unavailable state.
    """
    client = FakeClient(override={"f.file_path AS unit": degraded})
    result = V.code_units(client, PROJECT)

    assert result["state"] == "unavailable"
    assert result["reason"] == "contract_mismatch"
    assert result["code_units"] == []
    assert "did not run the query as written" in result["message"]


def test_degradation_on_a_later_query_is_caught_too():
    """The units query can succeed while an aggregate degrades. Reading that as
    zero coupling everywhere would look entirely plausible."""
    client = FakeClient(override={"AS fan_in": DEGRADED_COMMA_JOIN})
    result = V.code_units(client, PROJECT)
    assert result["state"] == "unavailable"


def test_an_empty_graph_and_a_graph_with_no_code_report_different_states():
    empty = FakeClient(
        replies={
            "f.file_path AS unit": {"columns": ["unit"], "rows": [], "total": 0},
            "AS fan_in": {"columns": ["unit", "fan_in"], "rows": [], "total": 0},
            "AS fan_out": {"columns": ["unit", "fan_out"], "rows": [], "total": 0},
        }
    )
    assert V.code_units(empty, PROJECT)["state"] == "empty_index"

    docs_only = FakeClient(
        replies={
            "f.file_path AS unit": {
                "columns": ["unit"],
                "rows": [["README.md"], ["docs/guide.md"]],
                "total": 2,
            },
            "AS fan_in": {"columns": ["unit", "fan_in"], "rows": [], "total": 0},
            "AS fan_out": {"columns": ["unit", "fan_out"], "rows": [], "total": 0},
        }
    )
    assert V.code_units(docs_only, PROJECT)["state"] == "indexed_no_summary"


def test_total_reports_the_population_and_shown_reports_the_slice():
    result = V.code_units(FakeClient(), PROJECT, limit=1)
    assert result["total"] == 3
    assert result["shown"] == 1
    assert len(result["code_units"]) == 1


def test_the_limit_is_bounded_at_both_ends():
    assert V.code_units(FakeClient(), PROJECT, limit=0)["shown"] == 1
    huge = V.code_units(FakeClient(), PROJECT, limit=10_000)
    assert huge["shown"] == 3


def test_ordering_is_identical_across_two_identical_requests():
    first = V.code_units(FakeClient(), PROJECT)
    second = V.code_units(FakeClient(), PROJECT)
    assert first["code_units"] == second["code_units"]


def test_counts_arrive_as_strings_and_are_returned_as_integers():
    """query_graph returns every value as a string, including aggregates."""
    result = V.code_units(FakeClient(), PROJECT)
    for row in result["code_units"]:
        assert isinstance(row["fan_in"], int)
        assert isinstance(row["fan_out"], int)


@pytest.mark.parametrize(
    "exc",
    [CbmError("engine child died"), CbmToolError("upstream tool failed")],
    ids=["transport", "tool"],
)
def test_engine_failures_become_a_state_rather_than_an_exception(exc):
    """call_tool documents both. Unhandled they leave the route as a 500, and the
    Console shows a blank table instead of saying the graph is unavailable.

    tool_router wraps these for every other caller through its own decorator.
    This module does not use that decorator, so it has to catch them itself.
    """

    class Boom:
        def call_tool(self, name, arguments, timeout=None):
            raise exc

    result = V.code_units(Boom(), PROJECT)

    assert result["state"] == "unavailable"
    assert result["reason"] == "graph_unavailable"
    assert result["code_units"] == []


def test_a_language_the_table_does_not_enumerate_is_still_shown():
    """The engine parses 158 languages. An allowlist of code extensions reports
    "no source files found" on a project full of source in any language it forgot,
    which the first draft did to .ps1 in MARM's own tree."""
    client = FakeClient(
        replies={
            "f.file_path AS unit": {
                "columns": ["unit"],
                "rows": [["scripts/deploy.ps1"], ["src/main.rs"], ["lib/thing.ex"]],
                "total": 3,
            },
            "AS fan_in": {"columns": ["unit", "fan_in"], "rows": [], "total": 0},
            "AS fan_out": {"columns": ["unit", "fan_out"], "rows": [], "total": 0},
        }
    )
    result = V.code_units(client, PROJECT)

    assert result["state"] == "ready"
    assert [row["unit"] for row in result["code_units"]] == [
        "lib/thing.ex",
        "scripts/deploy.ps1",
        "src/main.rs",
    ]


def test_the_unavailable_helper_matches_the_shape_the_browser_renders():
    """Every no-table path returns this, including the one in the endpoint where
    no client exists, so all four states reach the UI the same way."""
    body = V.unavailable("graph_unavailable")

    assert body == {
        "state": "unavailable",
        "reason": "graph_unavailable",
        "total": 0,
        "shown": 0,
        "code_units": [],
    }
    # The keys the browser reads on every response, whatever the state.
    shared = {"state", "total", "shown", "code_units"}
    assert shared <= set(body)
    assert shared <= set(V.code_units(FakeClient(), PROJECT))


def test_the_response_admits_fan_in_is_a_lower_bound():
    """`from package import module` attributes to a Folder node, never to the
    imported file, so the number is a floor and the UI must not claim otherwise."""
    assert V.code_units(FakeClient(), PROJECT)["fan_in_is_lower_bound"] is True


def test_code_graph_returns_a_bounded_file_import_snapshot():
    client = FakeClient(
        replies={
            "f.file_path AS unit": UNITS_REPLY,
            "count(DISTINCT a.file_path) AS fan_in": FAN_IN_REPLY,
            "count(DISTINCT b.file_path) AS fan_out": FAN_OUT_REPLY,
            "a.file_path AS source": {
                "columns": ["source", "target"],
                "rows": [
                    [
                        "marm-mcp-server/marm_mcp_server/core/memory.py",
                        "marm-mcp-server/marm_mcp_server/config/settings.py",
                    ],
                    [
                        "marm-mcp-server/marm_mcp_server/core/memory.py",
                        "marm-mcp-server/marm_mcp_server/config/settings.py",
                    ],
                    ["marm-mcp-server/marm_mcp_server/server.py", "README.md"],
                ],
                "total": 3,
            },
            "count(r) AS total": {"columns": ["total"], "rows": [["984"]], "total": 1},
        }
    )

    result = V.code_graph(client, PROJECT)

    assert result["state"] == "ready"
    assert result["total"] == {"code_units": 3, "import_edges": 984}
    assert result["rendered"] == {"code_units": 3, "import_edges": 1}
    assert result["truncated"] is True
    assert result["nodes"][0]["id"].endswith("memory.py")
    assert result["edges"] == [
        {
            "source": "marm-mcp-server/marm_mcp_server/core/memory.py",
            "target": "marm-mcp-server/marm_mcp_server/config/settings.py",
            "relation": "imports",
            "count": 2,
        }
    ]
    imports_call = next(
        args for name, args in client.calls if "AS source" in args.get("query", "")
    )
    assert imports_call["max_rows"] == V.GRAPH_EDGE_LIMIT


def test_code_graph_unavailable_state_keeps_its_visualization_shape():
    result = V.code_graph(FakeClient(), "has spaces and quotes '")

    assert result == {
        "state": "unavailable",
        "reason": "invalid_project",
        "total": {"code_units": 0, "import_edges": 0},
        "rendered": {"code_units": 0, "import_edges": 0},
        "truncated": False,
        "nodes": [],
        "edges": [],
    }


def test_code_graph_neighborhood_uses_only_bounded_server_owned_templates():
    node_id = "marm-mcp-server/marm_mcp_server/core/memory.py"
    client = FakeClient(
        replies={
            f"WHERE a.file_path = '{node_id}' RETURN a.file_path AS source": {
                "columns": ["source", "target"],
                "rows": [
                    [node_id, "marm-mcp-server/marm_mcp_server/config/settings.py"]
                ],
                "total": 1,
            },
            f"WHERE b.file_path = '{node_id}' RETURN a.file_path AS source": {
                "columns": ["source", "target"],
                "rows": [["marm-mcp-server/marm_mcp_server/server.py", node_id]],
                "total": 1,
            },
            f"WHERE a.file_path = '{node_id}' RETURN count(r) AS total": {
                "columns": ["total"],
                "rows": [["1"]],
                "total": 1,
            },
            f"WHERE b.file_path = '{node_id}' RETURN count(r) AS total": {
                "columns": ["total"],
                "rows": [["1"]],
                "total": 1,
            },
        }
    )

    result = V.code_graph_neighborhood(client, PROJECT, node_id)

    assert result["state"] == "ready"
    assert result["seed_id"] == node_id
    assert result["total_imports"] == result["rendered_imports"] == 2
    assert {node["id"] for node in result["nodes"]} == {
        node_id,
        "marm-mcp-server/marm_mcp_server/config/settings.py",
        "marm-mcp-server/marm_mcp_server/server.py",
    }
    assert all(
        args["max_rows"] == V.NEIGHBORHOOD_EDGE_LIMIT for _, args in client.calls[:2]
    )


def test_code_graph_neighborhood_rejects_query_shaped_node_ids_before_engine_call():
    client = FakeClient()

    result = V.code_graph_neighborhood(client, PROJECT, "x' RETURN n; MATCH (n)")

    assert result["reason"] == "invalid_node"
    assert client.calls == []


def test_code_graph_neighborhood_rejects_backslash_before_engine_call():
    client = FakeClient()

    result = V.code_graph_neighborhood(client, PROJECT, r"path\\")

    assert result["reason"] == "invalid_node"
    assert client.calls == []
