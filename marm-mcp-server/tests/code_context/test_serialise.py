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
    out = serialise(_ctx(symbols=[_traced()]), "t", detail=2)
    symbol = out["symbols"][0]

    assert symbol["label"] == "Method"
    assert symbol["provenance"]["risk"] == "CRITICAL"


def test_a_seeded_symbol_has_no_provenance():
    """None rather than zeros. Four flat zero-valued keys would assert a
    hop-0 heuristic edge at confidence 0.0, which is a claim, not an absence."""
    out = serialise(_ctx(symbols=[_seeded()]), "t", detail=2)

    assert out["symbols"][0]["provenance"] is None


def test_provenance_reports_how_the_symbol_was_reached():
    out = serialise(_ctx(symbols=[_traced()]), "t", detail=2)

    assert out["symbols"][0]["provenance"] == {
        "hop": 1,
        "strategy": "lsp",
        "confidence": 0.9712,
        "risk": "CRITICAL",
    }


def test_risk_alone_is_enough_to_report_provenance():
    """A trace row can carry a risk without a resolved strategy; that is still
    provenance, and collapsing it to None would lose the only thing known."""
    out = serialise(
        _ctx(symbols=[Symbol("a.x", "x", "", "", 0, 0, risk="HIGH")]), "t", detail=2
    )

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


def _bulky():
    ctx = _ctx(symbols=[_seeded()])
    ctx.symbols[0].source = "def helper():\n    return 1\n"
    ctx.memories = [{"id": "1", "content": "why it caches", "similarity": 0.8}]
    return ctx


def test_detail_one_returns_markdown_without_repeating_it_as_fields():
    """`markdown` already contains the source and the memory text. Measured on
    one real composition: 42,235 bytes total, `markdown` 17,465 of it and
    `symbols[].source` another 12,131 -- the identical text, twice. An agent
    reads the markdown and stops, so the default must not ship both."""
    out = serialise(_bulky(), "t", detail=1)

    assert out["markdown"]
    assert "symbols" not in out
    assert "memories" not in out


def test_counts_survive_every_level():
    """Dropping the arrays must not lose the fact that there WERE any. Two
    integers is the difference between "nothing matched" and "a lot matched"."""
    for level in (1, 2, 3):
        out = serialise(_bulky(), "t", detail=level)
        assert out["symbol_count"] == 1
        assert out["memory_count"] == 1


def test_detail_two_gives_metadata_without_the_bodies():
    """Enough to decide where to look, without re-reading what the markdown
    already said."""
    out = serialise(_bulky(), "t", detail=2)

    symbol = out["symbols"][0]
    assert symbol["file_path"] == "a.py"
    assert "source" not in symbol
    assert "content" not in out["memories"][0]
    assert out["memories"][0]["similarity"] == 0.8


def test_detail_three_is_what_a_renderer_needs():
    out = serialise(_bulky(), "t", detail=3)

    assert out["symbols"][0]["source"].startswith("def helper()")
    assert out["memories"][0]["content"] == "why it caches"


def test_the_applied_level_is_reported_back():
    """A caller that relied on the server default needs to know what it got."""
    assert serialise(_bulky(), "t", detail=2)["detail"] == 2


def test_out_of_range_detail_is_clamped_not_rejected():
    """A bad level should not fail a composition that already succeeded."""
    assert serialise(_bulky(), "t", detail=9)["detail"] == 3
    assert serialise(_bulky(), "t", detail=-1)["detail"] == 1


def test_the_graph_is_a_separate_axis_from_detail():
    """`include_graph` is a visualisation payload, not more of the same
    content, so the quietest level can still carry it if asked."""
    ctx = _bulky()
    ctx.graph_edges = [("a", "b", 1.0)]

    assert serialise(ctx, "t", detail=1, include_graph=True)["graph_edges"]
    assert "graph_edges" not in serialise(ctx, "t", detail=3)
