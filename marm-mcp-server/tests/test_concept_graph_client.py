"""Tests for core/graph_client.py's soft-fail in-process link into marm-graph.

Uses a fake CbmClient + monkeypatched tool_router.do_lookup rather than the
real 269MB codebase-memory-mcp binary (unavailable in this sandbox, same
constraint as marm_graph's own @requires_binary tests) -- these tests exercise
graph_client's own dispatch/soft-fail logic, not marm-graph's real search
quality, so a fake at this specific boundary is appropriate.
"""

from marm_mcp_server.core import graph_client
from marm_mcp_server.core.graph_supervisor import graph_supervisor


class _FakeClient:
    pass


def test_find_code_match_returns_none_when_graph_unavailable(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: False)
    assert graph_client.find_code_match("CbmClient", "proj-a") is None


def test_find_code_match_returns_none_when_client_is_none(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: None)
    assert graph_client.find_code_match("CbmClient", "proj-a") is None


def test_find_code_match_soft_fails_on_no_project_status(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {"status": "no_project", "message": "..."},
    )
    assert graph_client.find_code_match("CbmClient", None) is None


def test_find_code_match_soft_fails_on_exception(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())

    def _raise(client, req):
        raise RuntimeError("subprocess died")

    monkeypatch.setattr(graph_client.R, "do_lookup", _raise)
    assert graph_client.find_code_match("CbmClient", "proj-a") is None


def test_find_code_match_returns_none_when_no_exact_name_match(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "results": [
                {"qualified_name": "marm_graph.core.cbm_client.OtherClass", "name": "OtherClass"}
            ]
        },
    )
    assert graph_client.find_code_match("CbmClient", "proj-a") is None


def test_find_code_match_matches_on_qualified_name_short_segment(monkeypatch):
    """search_graph rows aren't guaranteed a separate 'name' field -- matching
    against qualified_name's last dotted segment is the fallback."""
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "results": [
                {
                    "qualified_name": "marm_graph.core.cbm_client.CbmClient",
                    "label": "class",
                    "file_path": "marm_graph/core/cbm_client.py",
                }
            ]
        },
    )
    match = graph_client.find_code_match("CbmClient", "proj-a")
    assert match == {
        "qualified_name": "marm_graph.core.cbm_client.CbmClient",
        "label": "class",
        "file_path": "marm_graph/core/cbm_client.py",
    }


def test_find_code_match_matches_on_explicit_name_field(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "results": [
                {
                    "qualified_name": "some.deeply.nested.qn",
                    "name": "CbmClient",
                    "label": "class",
                    "file_path": "x.py",
                }
            ]
        },
    )
    match = graph_client.find_code_match("CbmClient", "proj-a")
    assert match["qualified_name"] == "some.deeply.nested.qn"


def test_find_code_match_finds_exact_match_ranked_below_top_bm25_result(monkeypatch):
    """symbol kind is BM25 discovery, not an exact-name lookup -- a
    higher-relevance non-exact row can legitimately outrank the true exact
    match. limit must be wide enough that the exact match is still in the
    returned set for the filter loop to find."""
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "results": [
                {
                    "qualified_name": "marm_graph.core.cbm_client.AuthMiddleware",
                    "name": "AuthMiddleware",
                },
                {
                    "qualified_name": "marm_graph.core.auth.auth",
                    "name": "auth",
                    "label": "function",
                    "file_path": "marm_graph/core/auth.py",
                },
            ]
        },
    )
    match = graph_client.find_code_match("auth", "proj-a")
    assert match == {
        "qualified_name": "marm_graph.core.auth.auth",
        "label": "function",
        "file_path": "marm_graph/core/auth.py",
    }


def test_find_code_match_requests_more_than_top_result(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    captured = {}

    def _capture(client, req):
        captured["limit"] = req.limit
        return {"results": []}

    monkeypatch.setattr(graph_client.R, "do_lookup", _capture)
    graph_client.find_code_match("CbmClient", "proj-a")
    assert captured["limit"] > 1
