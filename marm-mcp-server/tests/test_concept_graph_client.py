from conftest import requires_binary

from marm_mcp_server.core import graph_client
from marm_mcp_server.core.graph_supervisor import graph_supervisor


class _FakeClient:
    pass


def test_find_code_match_reports_unavailable_when_graph_unavailable(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: False)
    assert graph_client.find_code_match("CbmClient", "proj-a") == {
        "status": "unavailable"
    }


def test_find_code_match_reports_unavailable_when_client_is_none(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: None)
    assert graph_client.find_code_match("CbmClient", "proj-a") == {
        "status": "unavailable"
    }


def test_find_code_match_soft_fails_on_no_project_status(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {"status": "no_project", "message": "..."},
    )
    assert graph_client.find_code_match("CbmClient", None) == {"status": "unavailable"}


def test_find_code_match_soft_fails_on_exception(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())

    def _raise(client, req):
        raise RuntimeError("subprocess died")

    monkeypatch.setattr(graph_client.R, "do_lookup", _raise)
    assert graph_client.find_code_match("CbmClient", "proj-a") == {
        "status": "unavailable"
    }


def test_find_code_match_reports_no_match_when_no_exact_name_match(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "results": [
                {
                    "qualified_name": "marm_graph.core.cbm_client.OtherClass",
                    "name": "OtherClass",
                }
            ]
        },
    )
    assert graph_client.find_code_match("CbmClient", "proj-a") == {"status": "no_match"}


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
        "status": "matched",
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
    assert match["status"] == "matched"
    assert match["qualified_name"] == "some.deeply.nested.qn"


def test_find_code_match_filters_exact_results(monkeypatch):
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
        "status": "matched",
        "qualified_name": "marm_graph.core.auth.auth",
        "label": "function",
        "file_path": "marm_graph/core/auth.py",
    }


def test_find_code_match_requests_a_bounded_exact_name_pattern(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    captured = {}

    def _capture(client, req):
        captured["limit"] = req.limit
        captured["query"] = req.query
        return {"results": []}

    monkeypatch.setattr(graph_client.R, "do_lookup", _capture)
    graph_client.find_code_match("CbmClient", "proj-a")
    assert captured == {"limit": 200, "query": "^CbmClient$"}


def test_find_code_match_refuses_a_truncated_exact_lookup(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "has_more": True,
            "results": [{"qualified_name": "one.CbmClient", "name": "CbmClient"}],
        },
    )

    assert graph_client.find_code_match("CbmClient", "proj-a") == {
        "status": "ambiguous",
        "candidates": ["one.CbmClient"],
    }


def test_find_code_match_treats_a_malformed_result_list_as_unavailable(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R, "do_lookup", lambda client, req: {"results": {"bad": "shape"}}
    )

    assert graph_client.find_code_match("CbmClient", "proj-a") == {
        "status": "unavailable"
    }


@requires_binary
def test_find_code_match_resolves_an_exact_symbol_against_the_live_engine(
    monkeypatch, client, project
):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: client)

    match = graph_client.find_code_match("do_lookup", project)

    assert match["status"] == "matched", match
    assert match["qualified_name"].endswith(".do_lookup")
    assert match["file_path"].endswith("tool_router.py")


def test_find_code_match_refuses_ambiguous_exact_symbols(monkeypatch):
    monkeypatch.setattr(graph_supervisor, "is_available", lambda: True)
    monkeypatch.setattr(graph_supervisor, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(
        graph_client.R,
        "do_lookup",
        lambda client, req: {
            "results": [
                {"qualified_name": "one.Config", "name": "Config"},
                {"qualified_name": "two.Config", "name": "Config"},
            ]
        },
    )

    assert graph_client.find_code_match("Config", "proj-a") == {
        "status": "ambiguous",
        "candidates": ["one.Config", "two.Config"],
    }
