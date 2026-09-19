"""The ranker has to answer 'important for THIS task', not 'globally popular'."""

from marm_mcp_server.services.code_context.rank import personalised_pagerank


def test_hub_beats_leaf_when_both_are_reachable():
    """`trace` returns callers AND callees, so the real subgraph has both
    directions; that is what lets a widely-called symbol outrank a private one."""
    edges = [
        ("a", "hub", 1.0),
        ("hub", "a", 0.5),
        ("b", "hub", 1.0),
        ("hub", "b", 0.5),
        ("c", "hub", 1.0),
        ("hub", "c", 0.5),
        ("a", "leaf", 1.0),
        ("leaf", "a", 0.5),
    ]
    r = personalised_pagerank(edges, {"a": 1.0})
    assert r["hub"] > r["leaf"]


def test_personalisation_actually_personalises():
    """Same graph, different seed -> different winner. Otherwise it is just PageRank."""
    edges = [("x", "x_child", 1.0), ("y", "y_child", 1.0)]
    from_x = personalised_pagerank(edges, {"x": 1.0})
    from_y = personalised_pagerank(edges, {"y": 1.0})
    assert from_x["x_child"] > from_x["y_child"]
    assert from_y["y_child"] > from_y["x_child"]


def test_edge_weight_is_respected():
    edges = [("s", "confident", 0.9), ("s", "guessed", 0.1)]
    r = personalised_pagerank(edges, {"s": 1.0})
    assert r["confident"] > r["guessed"]


def test_dangling_mass_returns_to_seeds_not_uniformly():
    """A sink must not bleed rank into unrelated nodes."""
    edges = [("seed", "sink", 1.0), ("unrelated", "other", 1.0)]
    r = personalised_pagerank(edges, {"seed": 1.0})
    assert r["seed"] > r["unrelated"]
    assert r["unrelated"] == 0.0 or r["seed"] > r["unrelated"] * 5


def test_empty_graph_is_not_a_crash():
    assert personalised_pagerank([], {}) == {}


def test_unknown_seed_cannot_hijack_the_ranking():
    """A seed that resolved to nothing must not hold all the restart mass."""
    edges = [("a", "b", 1.0)]
    r = personalised_pagerank(edges, {"not-in-graph": 1.0})
    assert set(r) == {"a", "b"}
    assert sum(r.values()) > 0


def test_self_loop_is_ignored():
    r = personalised_pagerank([("a", "a", 1.0), ("a", "b", 1.0)], {"a": 1.0})
    assert r["b"] > 0


def test_ranks_form_a_distribution():
    edges = [("a", "b", 1.0), ("b", "c", 1.0), ("c", "a", 1.0)]
    r = personalised_pagerank(edges, {"a": 1.0})
    assert abs(sum(r.values()) - 1.0) < 1e-6
