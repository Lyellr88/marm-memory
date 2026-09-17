"""Tests for the public response shape.

`serialise` -- not `build_code_context` -- is what defines the JSON every agent
receives over both transports. It had no coverage at all before these tests, and
it is the function every shape change lands in. It is pure, so none of this
needs a live graph backend.
"""

from marm_mcp_server.services.code_context import serialise
from marm_mcp_server.services.code_context.compose import Context, Symbol


def _ctx(**kw):
    ctx = Context(project={"name": "p", "root_path": "/x/proj"}, task="t", **kw)
    return ctx


def _seeded():
    return Symbol("a.helper", "helper", "Function", "a.py", 1, 9, seeded=True)


def _traced():
    """A symbol that arrived through the call graph, as compose builds one."""
    return Symbol(
        "a.caller",
        "caller",
        "Method",
        "b.py",
        4,
        20,
        risk="CRITICAL",
        hop=1,
        strategy="lsp",
        confidence=0.9712,
    )


def test_label_carries_the_code_kind_not_the_risk():
    """The defect this guards: a trace row's `risk` used to be stored in
    `label`, so a symbol reported CRITICAL where a reader expects Method -- in
    the Console badge and in the agent markdown alike."""
    out = serialise(_ctx(symbols=[_traced()]), "t")
    symbol = out["symbols"][0]

    assert symbol["label"] == "Method"
    assert symbol["provenance"]["risk"] == "CRITICAL"


def test_a_seeded_symbol_has_no_provenance():
    """None rather than zeros. Four flat zero-valued keys would assert a
    hop-0 heuristic edge at confidence 0.0, which is a claim, not an absence."""
    out = serialise(_ctx(symbols=[_seeded()]), "t")

    assert out["symbols"][0]["provenance"] is None


def test_provenance_reports_how_the_symbol_was_reached():
    out = serialise(_ctx(symbols=[_traced()]), "t")

    assert out["symbols"][0]["provenance"] == {
        "hop": 1,
        "strategy": "lsp",
        "confidence": 0.9712,
        "risk": "CRITICAL",
    }


def test_risk_alone_is_enough_to_report_provenance():
    """A trace row can carry a risk without a resolved strategy; that is still
    provenance, and collapsing it to None would lose the only thing known."""
    out = serialise(_ctx(symbols=[Symbol("a.x", "x", "", "", 0, 0, risk="HIGH")]), "t")

    assert out["symbols"][0]["provenance"]["risk"] == "HIGH"


def test_graph_edges_are_absent_unless_asked_for():
    """Opt-in on purpose: an agent reads `markdown` and stops, so charging every
    caller several KB for a view only the Console renders is wasted budget."""
    ctx = _ctx(symbols=[_seeded()])
    ctx.graph_edges = [("a", "b", 1.0)]

    assert "graph_edges" not in serialise(ctx, "t")
    assert serialise(ctx, "t", include_graph=True)["graph_edges"] == [["a", "b", 1.0]]


def test_project_is_a_fixed_shape_not_the_engine_row():
    """The engine names a project after its absolute path, so a caller wanting a
    label needs short_name and one wanting to re-query needs name."""
    out = serialise(_ctx(), "t")

    assert out["project"] == {
        "name": "p",
        "short_name": "proj",
        "root_path": "/x/proj",
    }
