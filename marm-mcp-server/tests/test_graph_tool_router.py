"""Tests for the 5-tool intent router."""

import subprocess

import pytest
from conftest import requires_binary

from marm_graph.core import tool_router as R
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)

# ── pure logic ──────────────────────────────────────────────────────


def test_qn_regex_matches_hyphenated_project_prefix():
    qn = "C-Users-lyell-Desktop-x.marm_graph.core.cbm_client.CbmClient.__init__"
    assert R._QN_RE.match(qn)


def test_qn_regex_rejects_bare_symbol_and_natural_language():
    assert not R._QN_RE.match("CbmClient")
    assert not R._QN_RE.match("update user settings")
    assert not R._QN_RE.match("CbmClient.call_tool")  # only 1 dot -> discovery


def test_bound_trims_oversized_result_list():
    # ~1.5MB of results, comfortably over the 1MB default cap.
    big = {"results": [{"x": "y" * 300} for _ in range(5000)]}
    bounded = R._bound(dict(big))
    assert bounded.get("_marm_graph_truncated") is True
    assert len(bounded["results"]) < 5000


def test_bound_passes_small_response_untouched():
    small = {"results": [{"a": 1}]}
    assert R._bound(dict(small)) == small


def test_bound_clips_oversized_non_list_response():
    # A single huge string with no trimmable list key (e.g. a giant snippet).
    # Stage-1 list trimming can't help here, so the hard ceiling must still hold.
    out = R._bound({"qualified_name": "x", "code": "z" * 2_000_000})
    assert out.get("_marm_graph_truncated") is True
    assert R._size(out) <= R.MAX_RESPONSE_BYTES
    assert out["code"].endswith(R._CLIP_MARK)


def test_bound_clips_oversized_non_trimmable_list():
    # A huge list under a key that is NOT in _TRIMMABLE_LIST_KEYS: stage 1 skips
    # it, stage 2 clips the strings inside it. Guarantee must still hold.
    out = R._bound({"node_labels": [{"label": "L" * 2000} for _ in range(1000)]})
    assert out.get("_marm_graph_truncated") is True
    assert R._size(out) <= R.MAX_RESPONSE_BYTES


def test_safe_converts_backend_error(monkeypatch):
    @R.safe
    def boom(client, req):
        raise R.CbmError("child dead")

    out = boom(None, None)
    assert out["status"] == "error" and "unavailable" in out["message"]


# ── engine 0.10.5 columnar conversion ───────────────────────────────
#
# The payloads below are representative samples taken from engine 0.10.5, not a
# complete upstream contract: column names and nesting are exactly as captured,
# while row counts are reduced and the architecture fixture carries 5 of its 13
# aspects. Do not read them as the full response shape.
#
# They are replayed rather than re-fetched because these tests assert on the
# arguments MARM sends, which the real binary cannot report, and because the
# failure being guarded against is silent: a missing format:"json" returns prose
# in a dict and raises nothing. The same paths are still exercised end to end
# against the real binary further down.

SEARCH_GRAPH_0105 = {
    "total": 1,
    "search_mode": "bm25",
    "cols": ["qn", "label", "file", "lines", "rank"],
    "rows": [["pkg.mod.notebook_dispatch", "Function", "pkg/mod.py", "321-347", -22.7]],
    "has_more": False,
}

SEARCH_GRAPH_NAME_PATTERN_0105 = {
    "total": 1,
    "count": 1,
    "cols": ["name", "label", "lines", "in", "out"],
    "groups": [
        {
            "qn_prefix": "pkg.mod.MARM",
            "file": "pkg/mod.py",
            "rows": [["store_memory", "Method", "274-281", 84, 1]],
        }
    ],
    "has_more": False,
}

SEARCH_CODE_0105 = {
    "cols": ["qn", "label", "file", "lines", "matches", "in", "out"],
    "rows": [["pkg.mod.call_tool", "Method", "pkg/mod.py", "291-302", [296], 16, 1]],
    "raw_matches": {"cols": ["file", "line", "content"], "rows": []},
    "total_results": 1,
}

# Two callers sharing a name, differing only by group prefix. This is the real
# notebook_dispatch case that produced two withdrawn recall figures when keyed
# on name alone.
TRACE_0105 = {
    "function": "notebook_dispatch",
    "direction": "inbound",
    "callers_total": 2,
    "callers": {
        "cols": ["name", "hop", "strategy", "confidence"],
        "groups": [
            {
                "qn_prefix": "pkg.server_stdio",
                "rows": [["marm_notebook", 1, "heuristic", 0.28]],
            },
            {
                "qn_prefix": "pkg.endpoints.notebook",
                "rows": [["marm_notebook", 1, "lsp", 0.97]],
            },
        ],
    },
}

ARCHITECTURE_0105 = {
    "project": "p",
    "total_nodes": 10,
    "node_labels": {"cols": ["label", "count"], "rows": [["Function", 53]]},
    "languages": {"cols": ["language", "files"], "rows": [["Python", 17]]},
    "packages": {
        "cols": ["name", "nodes", "fan_in", "fan_out"],
        "rows": [["pkg", 3, 1, 2]],
    },
    "entry_points": {"cols": ["qn", "file"], "rows": [["pkg.mod.main", "pkg/mod.py"]]},
    "boundaries": {"cols": ["from", "to", "calls"], "rows": [["tests", "pkg", 12]]},
}

IMPACT_0105 = {
    "impacted": [{"qualified_name": "pkg.mod.f"}],
    "impacted_total": 5,
    "impacted_shown": 1,
    "truncated": True,
    "changed_files": ["pkg/mod.py"],
}


class RecordingClient:
    """Replays canned upstream replies and records the arguments it received."""

    def __init__(self, **replies):
        self.replies = {"list_projects": {"projects": [{"name": "p"}]}, **replies}
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        if name not in self.replies:
            raise AssertionError(f"unexpected upstream call: {name}")
        return self.replies[name]

    def args_for(self, name) -> dict:
        return next(args for called, args in self.calls if called == name)


def test_every_columnar_call_sends_format_json():
    """A missing format:"json" degrades silently, so assert on the args, not the reply."""
    cases = [
        (
            "search_graph",
            lambda c: R.do_lookup(c, CodeLookupRequest(query="x", kind="symbol")),
            {"search_graph": SEARCH_GRAPH_0105},
        ),
        (
            "search_code",
            lambda c: R.do_lookup(c, CodeLookupRequest(query="x", kind="text")),
            {"search_code": SEARCH_CODE_0105},
        ),
        (
            "trace_path",
            lambda c: R.do_trace(c, GraphTraceRequest(function_name="f")),
            {"trace_path": TRACE_0105},
        ),
        (
            "get_architecture",
            lambda c: R.do_architecture(c, GraphArchitectureRequest()),
            {"get_architecture": ARCHITECTURE_0105, "get_graph_schema": {}},
        ),
        (
            "detect_changes",
            lambda c: R.do_impact(c, GraphImpactRequest()),
            {"detect_changes": IMPACT_0105},
        ),
    ]
    for tool, call, replies in cases:
        client = RecordingClient(**replies)
        call(client)
        assert client.args_for(tool).get("format") == "json", tool


def test_search_graph_rows_become_result_dicts():
    client = RecordingClient(search_graph=SEARCH_GRAPH_0105)
    out = R.do_lookup(client, CodeLookupRequest(query="x", kind="symbol"))

    assert "cols" not in out and "rows" not in out
    assert out["total"] == 1 and out["has_more"] is False
    row = out["results"][0]
    assert row["qualified_name"] == "pkg.mod.notebook_dispatch"
    assert row["file_path"] == "pkg/mod.py"
    assert row["label"] == "Function"
    assert (row["start_line"], row["end_line"]) == (321, 347)
    assert row["name"] == "notebook_dispatch"


def test_search_graph_name_pattern_groups_become_result_dicts():
    client = RecordingClient(search_graph=SEARCH_GRAPH_NAME_PATTERN_0105)
    out = R.do_lookup(client, CodeLookupRequest(query="^store_memory$", kind="symbol"))

    assert "groups" not in out
    assert out["total"] == 1 and out["has_more"] is False
    assert out["results"] == [
        {
            "name": "store_memory",
            "label": "Method",
            "lines": "274-281",
            "in": 84,
            "out": 1,
            "qualified_name": "pkg.mod.MARM.store_memory",
            "file_path": "pkg/mod.py",
        }
    ]


def test_search_code_rows_keep_the_0_9_key_names():
    client = RecordingClient(search_code=SEARCH_CODE_0105)
    out = R.do_lookup(client, CodeLookupRequest(query="x", kind="text"))

    row = out["results"][0]
    # search_code called the path `file`, where search_graph called it `file_path`.
    assert row["file"] == "pkg/mod.py"
    assert row["qualified_name"] == "pkg.mod.call_tool"
    assert row["match_lines"] == [296]
    assert (row["in_degree"], row["out_degree"]) == (16, 1)
    assert (row["start_line"], row["end_line"]) == (291, 302)
    assert row["node"] == "call_tool"
    assert out["raw_matches"] == []


def test_trace_keeps_two_same_named_callers_distinct():
    client = RecordingClient(trace_path=TRACE_0105)
    out = R.do_trace(client, GraphTraceRequest(function_name="notebook_dispatch"))

    callers = out["callers"]
    assert isinstance(callers, list) and len(callers) == 2
    assert {c["name"] for c in callers} == {"marm_notebook"}
    assert {c["qualified_name"] for c in callers} == {
        "pkg.server_stdio.marm_notebook",
        "pkg.endpoints.notebook.marm_notebook",
    }
    assert {c["strategy"] for c in callers} == {"heuristic", "lsp"}


def test_trace_sends_both_evidence_flags_with_their_defaults():
    client = RecordingClient(trace_path=TRACE_0105)
    R.do_trace(client, GraphTraceRequest(function_name="f"))
    sent = client.args_for("trace_path")
    assert sent["include_evidence"] is True
    assert sent["include_tests"] is False

    client = RecordingClient(trace_path=TRACE_0105)
    R.do_trace(client, GraphTraceRequest(function_name="f", include_tests=True))
    assert client.args_for("trace_path")["include_tests"] is True


def test_architecture_asks_for_every_aspect_and_flattens_each():
    """0.10.5 answers with a summary unless asked, dropping six 0.9.0 sections."""
    client = RecordingClient(
        get_architecture=ARCHITECTURE_0105, get_graph_schema={"node_labels": []}
    )
    out = R.do_architecture(client, GraphArchitectureRequest())

    assert client.args_for("get_architecture")["aspects"] == ["all"]
    # {label, count} rows are the deliberate target, matching engine 0.9.0 and the
    # counts agents rely on. The Console wants bare type-name strings instead, and
    # that belongs in the Console endpoint: normalizing here would strip the counts
    # from every agent to satisfy one UI table. See console-architecture-view spec.
    assert out["node_labels"] == [{"label": "Function", "count": 53}]
    # Column names drifted inside the aspects too, not just at the top level.
    assert out["languages"] == [{"language": "Python", "file_count": 17}]
    assert out["packages"][0]["node_count"] == 3
    assert out["boundaries"][0]["call_count"] == 12
    assert out["entry_points"][0] == {
        "qualified_name": "pkg.mod.main",
        "file": "pkg/mod.py",
        "name": "main",
    }


def test_impact_exposes_impacted_symbols_and_keeps_the_new_totals():
    client = RecordingClient(detect_changes=IMPACT_0105)
    out = R.do_impact(client, GraphImpactRequest())

    assert out["impacted_symbols"] == [{"qualified_name": "pkg.mod.f"}]
    assert "impacted" not in out
    assert out["impacted_total"] == 5 and out["truncated"] is True
    assert out["changed_files"] == ["pkg/mod.py"]


def test_converters_pass_lists_through_untouched():
    """An engine that reverts to list output must not be re-mangled."""
    already = [{"qualified_name": "a.b"}]
    assert R._rows_to_dicts(already) is already
    assert R._groups_to_callers(already) is already


def test_converters_tolerate_missing_keys():
    for bad in ({}, {"cols": ["a"]}, {"rows": [[1]]}, None, "text"):
        assert R._rows_to_dicts(bad) in ([], bad)
        assert R._groups_to_callers(bad) in ([], bad)
    assert R._groups_to_callers({"cols": ["name"], "groups": [None, {}]}) == []


def test_bound_trims_converted_caller_lists():
    """callers/callees are lists only after conversion, and can be the largest key."""
    out = R._bound({"callers": [{"qualified_name": "q" * 400} for _ in range(5000)]})
    assert out.get("_marm_graph_truncated") is True
    assert len(out["callers"]) < 5000
    assert R._size(out) <= R.MAX_RESPONSE_BYTES


# ── integration ─────────────────────────────────────────────────────


def test_resolve_project_autopicks_single():
    class FakeClient:
        def call_tool(self, name, args):
            assert name == "list_projects"
            assert args == {}
            return {"projects": [{"name": "only-project"}]}

    name, err = R.resolve_project(FakeClient(), None)
    assert err is None and name == "only-project"


@requires_binary
def test_do_index_status_and_list(client, project):
    listed = R.do_index(client, GraphIndexRequest(action="list"))
    assert any(p["name"] == project for p in listed["projects"])
    status = R.do_index(client, GraphIndexRequest(action="status", project=project))
    assert status["status"] == "ready"


@requires_binary
def test_do_lookup_symbol_discovery(client, project):
    out = R.do_lookup(client, CodeLookupRequest(query="CbmClient", project=project))
    assert out["results"] and out.get("total", 0) >= 1


@requires_binary
def test_do_lookup_exact_name_pattern_normalizes_grouped_results(client, project):
    out = R.do_lookup(
        client,
        CodeLookupRequest(
            query="^do_lookup$", project=project, kind="symbol", limit=200
        ),
    )

    assert out.get("has_more") is False, out
    assert any(
        row.get("name") == "do_lookup"
        and row.get("qualified_name", "").endswith(".do_lookup")
        and row.get("file_path", "").endswith("tool_router.py")
        for row in out.get("results", [])
    ), out


@requires_binary
def test_do_lookup_snippet_auto_routes_on_qualified_name(client, project):
    discovery = R.do_lookup(
        client, CodeLookupRequest(query="CbmClient", project=project)
    )
    qn = next(
        (
            row.get("qualified_name")
            for row in discovery.get("results", [])
            if row.get("qualified_name")
        ),
        None,
    )
    assert qn, discovery

    out = R.do_lookup(client, CodeLookupRequest(query=qn, project=project))
    # get_code_snippet returns node metadata w/ file location, not a results list
    assert "qualified_name" in out or "file_path" in out


@requires_binary
def test_do_lookup_text_uses_search_code(client, project):
    out = R.do_lookup(
        client, CodeLookupRequest(query="isError", kind="text", project=project)
    )
    assert isinstance(out.get("results"), list) and out["results"]


@requires_binary
def test_do_trace_returns_structured_result(client, project):
    out = R.do_trace(
        client,
        GraphTraceRequest(
            function_name="call_tool", direction="inbound", project=project
        ),
    )
    assert out.get("status") != "error"
    assert out.get("function") == "call_tool"
    assert out.get("direction") == "inbound"
    assert isinstance(out.get("callers"), list)
    # Engine 0.9.0 answered this with an empty list because it could not resolve
    # imports when the package root sat below the repository root. That is the
    # defect 0.10.5 fixes, so an empty answer here is now a regression rather
    # than an acceptable outcome.
    assert out["callers"], "no callers resolved; check the engine version"
    first = out["callers"][0]
    assert first["qualified_name"].endswith("." + first["name"])
    assert first["strategy"] in {"lsp", "language_rule", "heuristic", "unresolved"}
    assert isinstance(first["confidence"], (int, float))


@requires_binary
def test_do_trace_omits_evidence_when_it_is_turned_off(client, project):
    out = R.do_trace(
        client,
        GraphTraceRequest(
            function_name="call_tool",
            direction="inbound",
            project=project,
            include_evidence=False,
        ),
    )
    assert out["callers"], out
    assert "strategy" not in out["callers"][0]
    assert "confidence" not in out["callers"][0]


@pytest.fixture(scope="session")
def tested_symbol_project(graph_client, tmp_path_factory):
    """A repo with one production caller and one test caller of the same function.

    The marm_graph fixture project indexes no tests, so it cannot show what
    include_tests does. This is the smallest tree that can: 23 nodes.
    """
    repo = tmp_path_factory.mktemp("include-tests-fixture")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "core.py").write_text(
        "def target():\n    return 1\n\n\ndef production_caller():\n    return target()\n",
        encoding="utf-8",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_core.py").write_text(
        "from pkg.core import target\n\n\ndef test_target():\n    assert target() == 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    result = graph_client.call_tool(
        "index_repository", {"repo_path": str(repo), "mode": "moderate"}
    )
    name = result.get("project")
    assert name, f"index_repository returned no project name: {result}"
    return name


@requires_binary
def test_include_tests_decides_whether_test_callers_come_back(
    client, tested_symbol_project
):
    """The observable behavior, not just that the flag was transmitted."""

    def callers(**kwargs):
        out = R.do_trace(
            client,
            GraphTraceRequest(
                function_name="target",
                project=tested_symbol_project,
                direction="inbound",
                **kwargs,
            ),
        )
        return {c["qualified_name"].rsplit(".", 1)[-1] for c in out["callers"]}

    assert callers() == {"production_caller"}
    assert callers(include_tests=True) == {"production_caller", "test_target"}


@requires_binary
def test_do_architecture_folds_in_schema(client, project):
    out = R.do_architecture(client, GraphArchitectureRequest(project=project))
    assert isinstance(out.get("node_labels"), list)
    assert "schema" in out
    # 0.10.5 answers with a summary unless every aspect is requested, and these
    # six are the ones it drops. They are part of 0.9.0's response contract.
    for aspect in (
        "routes",
        "hotspots",
        "boundaries",
        "layers",
        "clusters",
        "file_tree",
    ):
        assert isinstance(out.get(aspect), list), aspect


@requires_binary
def test_do_impact_returns_dict(client, project):
    out = R.do_impact(client, GraphImpactRequest(project=project))
    # isinstance(dict) alone also passes for an error dict ({"status": "error", ...})
    # since that's a dict too — assert it's not an error response, distinctly.
    assert out.get("status") != "error"
    assert isinstance(out, dict)


@requires_binary
def test_bad_project_returns_error(client):
    out = R.do_lookup(
        client, CodeLookupRequest(query="X", project="nonexistent-project-xyz")
    )
    assert out["status"] == "error"
