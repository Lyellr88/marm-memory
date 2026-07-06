"""Tests for the 5-tool intent router."""

from marm_graph.core import tool_router as R
from marm_graph.core.models import (
    CodeLookupRequest,
    GraphArchitectureRequest,
    GraphImpactRequest,
    GraphIndexRequest,
    GraphTraceRequest,
)
from conftest import requires_binary


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
    # The upstream graph engine can validly return an empty caller/callee list
    # depending on how the current binary models Python method dispatch. The
    # router contract is that a valid trace request returns a structured,
    # bounded trace response rather than an error envelope.
    assert out.get("function") == "call_tool"
    assert out.get("direction") == "inbound"
    assert isinstance(out.get("callers"), list)


@requires_binary
def test_do_architecture_folds_in_schema(client, project):
    out = R.do_architecture(client, GraphArchitectureRequest(project=project))
    assert isinstance(out.get("node_labels"), list)
    assert "schema" in out


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
