"""Pipeline behaviour, against a stub engine so the assertions are about ranking."""

import pytest

from marm_mcp_server.services.code_context.backend import GraphUnavailable
from marm_mcp_server.services.code_context.compose import build
from marm_mcp_server.services.code_context.format import render


class Stub:
    """Minimal stand-in for the MARM HTTP client."""

    def __init__(
        self,
        root,
        *,
        results=None,
        trace=None,
        memories=None,
        links=None,
        memory_project=None,
    ):
        self.root = str(root)
        self._results = results or []
        self._trace = trace or {}
        self._memories = memories or []
        self._links = links or []
        self.memory_project = memory_project
        self.searches = []
        self.recall_queries = []

    def projects(self):
        return [{"name": "proj", "root_path": self.root}]

    def search(self, project, query, limit=25, semantic=None):
        self.searches.append(query)
        return self._results

    def trace(self, project, symbol, depth=2, direction="both"):
        return self._trace.get(symbol, {})

    async def recall(self, query, limit=5, project=None, search_all=True):
        self.recall_queries.append(query)
        return self._memories

    def memory_links(self, project):
        return self._links

    def binding(self, project):
        return {"memory_project": self.memory_project} if self.memory_project else None

    def impact(self, project, depth=2):
        return {}


def _row(name, qn, line=1, end=3, label="Function"):
    return {
        "qualified_name": qn,
        "name": name,
        "label": label,
        "file_path": "m.py",
        "start_line": line,
        "end_line": end,
    }


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "m.py").write_text(
        "def helper():\n    return 1\n\n"
        "def central():\n    return helper()\n\n"
        "def caller():\n    return central()\n"
    )
    return tmp_path


@pytest.mark.asyncio
async def test_unindexed_project_explains_itself(tmp_path):
    class Empty(Stub):
        def projects(self):
            return []

    with pytest.raises(GraphUnavailable) as e:
        await build(Empty(tmp_path), "anything", cwd=str(tmp_path))
    assert "index" in str(e.value).lower()


@pytest.mark.asyncio
async def test_returns_source_read_from_disk(repo):
    c = Stub(repo, results=[_row("helper", "proj.m.helper", 1, 2)])
    ctx = await build(c, "helper", cwd=str(repo))
    assert ctx.symbols and "return 1" in ctx.symbols[0].source


@pytest.mark.asyncio
async def test_call_graph_promotes_a_symbol_the_search_ranked_lower(repo):
    """The point of the ranker: search order is not the answer."""
    results = [
        _row("caller", "proj.m.caller", 7, 8),
        _row("central", "proj.m.central", 4, 5),
    ]
    trace = {
        "caller": {
            "callees": [
                {
                    "qualified_name": "proj.m.central",
                    "name": "central",
                    "hop": 1,
                    "confidence": 0.9,
                }
            ]
        }
    }
    ctx = await build(Stub(repo, results=results, trace=trace), "caller", cwd=str(repo))
    names = [s.name for s in ctx.symbols]
    assert "central" in names


@pytest.mark.asyncio
async def test_budget_is_respected(repo):
    (repo / "m.py").write_text("\n".join(f"line {i}" for i in range(400)))
    c = Stub(repo, results=[_row("big", "proj.m.big", 1, 400)])
    ctx = await build(c, "big", cwd=str(repo), budget=50)
    assert sum(len(s.source) for s in ctx.symbols) < 4000


@pytest.mark.asyncio
async def test_memories_are_joined_in(repo):
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"content": "helper caches because the API rate-limits"}],
    )
    out = render(await build(c, "helper", cwd=str(repo)))
    assert "rate-limits" in out and "What memory knows" in out


@pytest.mark.asyncio
async def test_the_memories_kept_are_the_best_not_the_first_seen(repo):
    """`collected` is built probe by probe, so without an explicit sort the cut
    keeps discovery order and presents it as if it were a ranking. A strong
    memory found late must beat a weak one found early."""
    memories = [
        {"content": f"m{i}", "similarity": s} for i, s in enumerate([0.10, 0.95, 0.20])
    ]
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=memories,
        memory_project="proj",
    )

    ctx = await build(c, "helper", cwd=str(repo))

    assert [m["content"] for m in ctx.memories][:1] == ["m1"]
    sims = [m["similarity"] for m in ctx.memories]
    assert sims == sorted(sims, reverse=True)


@pytest.mark.asyncio
async def test_a_trace_symbol_keeps_its_risk_out_of_its_label(repo):
    """The engine returns `risk` on a trace row. Storing it in `label` made a
    symbol report CRITICAL where a code kind belongs -- visible in the Console
    badge and in the agent markdown, which renders label as `(kind)`."""
    trace = {
        "proj.m.helper": {
            "callers": [
                {
                    "qualified_name": "proj.m.caller",
                    "name": "caller",
                    "risk": "CRITICAL",
                    "hop": 1,
                    "strategy": "lsp",
                    "confidence": 0.97,
                }
            ]
        }
    }

    # Query-aware on purpose. The shared Stub returns every row for any query,
    # which would seed `caller` directly and never exercise the trace path at
    # all -- the symbol has to be findable by the backfill search but absent
    # from the seed results.
    class Backfill(Stub):
        def search(self, project, query, limit=25, semantic=None):
            self.searches.append(query)
            if query == "caller":
                return [_row("caller", "proj.m.caller", 4, 6, label="Method")]
            return self._results

    c = Backfill(repo, results=[_row("helper", "proj.m.helper", 1, 2)], trace=trace)

    ctx = await build(c, "helper", cwd=str(repo))
    caller = next((s for s in ctx.symbols if s.name == "caller"), None)

    assert caller is not None
    assert caller.label != "CRITICAL"
    assert caller.risk == "CRITICAL"
    assert (caller.hop, caller.strategy, caller.confidence) == (1, "lsp", 0.97)


@pytest.mark.asyncio
async def test_the_ranked_edges_survive_for_a_caller_that_wants_them(repo):
    """PageRank consumes a raw duplicated edge list whose repetition IS the
    weighting; the aggregated view is one record per ordered pair."""
    trace = {
        "proj.m.helper": {
            "callers": [{"qualified_name": "proj.m.caller", "name": "caller", "hop": 1}]
        }
    }
    c = Stub(repo, results=[_row("helper", "proj.m.helper", 1, 2)], trace=trace)

    ctx = await build(c, "helper", cwd=str(repo))

    assert ctx.graph_edges
    pairs = [(a, b) for a, b, _ in ctx.graph_edges]
    assert len(pairs) == len(set(pairs))


@pytest.mark.asyncio
async def test_memory_links_are_filtered_to_shown_symbols(repo):
    """The API returns `qualified_name`; the concept DB column is
    `graph_qualified_name`. Reading only the latter matched nothing and left the
    section permanently empty, so both spellings must resolve."""
    links = [
        {
            "qualified_name": "proj.m.helper",
            "entity_name": "helper",
            "file_path": "m.py",
            "link_method": "exact_symbol",
        },
        {
            "graph_qualified_name": "proj.m.helper",
            "entity_name": "helper",
            "file_path": "m.py",
            "link_method": "exact_symbol",
        },
        {
            "qualified_name": "proj.m.absent",
            "entity_name": "absent",
            "file_path": "z.py",
            "link_method": "exact_symbol",
        },
    ]
    c = Stub(repo, results=[_row("helper", "proj.m.helper", 1, 2)], links=links)
    ctx = await build(c, "helper", cwd=str(repo))
    resolved = [
        ln.get("qualified_name") or ln.get("graph_qualified_name") for ln in ctx.links
    ]
    assert resolved == ["proj.m.helper", "proj.m.helper"]


@pytest.mark.asyncio
async def test_recall_failure_degrades_instead_of_failing_the_call(repo):
    class NoRecall(Stub):
        async def recall(self, *a, **k):
            raise GraphUnavailable("down")

    c = NoRecall(repo, results=[_row("helper", "proj.m.helper", 1, 2)])
    ctx = await build(c, "helper", cwd=str(repo))
    assert ctx.symbols and any("memory recall" in n for n in ctx.notes)


@pytest.mark.asyncio
async def test_empty_result_still_renders_actionable_text(repo):
    out = render(await build(Stub(repo), "nothing matches", cwd=str(repo)))
    assert "No indexed symbols matched" in out


@pytest.mark.asyncio
async def test_render_includes_the_stop_fetching_hint(repo):
    c = Stub(repo, results=[_row("helper", "proj.m.helper", 1, 2)])
    out = render(await build(c, "helper", cwd=str(repo)))
    assert "do not follow up" in out.lower()


@pytest.mark.asyncio
async def test_memories_about_another_project_are_filtered_out(repo):
    """One MARM server backs every agent, so recall crosses repositories."""
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"content": "the chrome extension debounces width changes"}],
    )
    ctx = await build(c, "helper", cwd=str(repo))
    assert ctx.memories == []


@pytest.mark.asyncio
async def test_memory_naming_a_shown_symbol_is_kept(repo):
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"content": "helper caches because the API rate-limits"}],
    )
    ctx = await build(c, "helper", cwd=str(repo))
    assert len(ctx.memories) == 1


@pytest.mark.asyncio
async def test_memory_naming_a_shown_file_is_kept(repo):
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"content": "m.py was rewritten to drop the global cache"}],
    )
    ctx = await build(c, "helper", cwd=str(repo))
    assert len(ctx.memories) == 1


@pytest.mark.asyncio
async def test_substring_match_does_not_count_as_naming(repo):
    """'helpers' must not match 'helper' -- word boundaries, not substrings."""
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"content": "unrelated note about helpfulness"}],
    )
    ctx = await build(c, "helper", cwd=str(repo))
    assert ctx.memories == []


@pytest.mark.asyncio
async def test_ambiguous_trace_does_not_silently_drop_the_call_graph(repo):
    """A bare name matching two symbols returns status=ambiguous with no edges."""
    calls = []

    class Amb(Stub):
        def trace(self, project, symbol, depth=2, direction="both"):
            calls.append(symbol)
            if symbol == "proj.m.caller":  # qualified: resolves
                return {
                    "callees": [
                        {
                            "qualified_name": "proj.m.central",
                            "name": "central",
                            "hop": 1,
                            "confidence": 0.9,
                        }
                    ]
                }
            return {"status": "ambiguous", "suggestions": []}

    c = Amb(repo, results=[_row("caller", "proj.m.caller", 7, 8)])
    ctx = await build(c, "caller", cwd=str(repo))
    assert calls and calls[0] == "proj.m.caller", "must trace by qualified_name first"
    assert ctx.graph_nodes > 0


@pytest.mark.asyncio
async def test_ambiguous_on_both_forms_is_survivable(repo):
    class AllAmb(Stub):
        def trace(self, *a, **k):
            return {"status": "ambiguous"}

    c = AllAmb(repo, results=[_row("helper", "proj.m.helper", 1, 2)])
    ctx = await build(c, "helper", cwd=str(repo))
    assert ctx.symbols  # seeds still carry the answer


@pytest.mark.asyncio
async def test_recall_probes_with_symbol_names_not_only_the_task(repo):
    """Memories are short headlines that name things, so a symbol is a far
    better probe than a prose question. Measured against the real store: the
    task "how does the content script inject CSS" returned nothing while the
    symbols it surfaced returned the relevant memories."""
    c = Stub(
        repo, results=[_row("injectEnhancedCSS", "proj.m.injectEnhancedCSS", 1, 2)]
    )
    await build(c, "how does the content script inject CSS", cwd=str(repo))
    assert "injectEnhancedCSS" in c.recall_queries


@pytest.mark.asyncio
async def test_generic_symbol_names_are_not_used_as_probes(repo):
    """Probing on `run` or `check` would pull unrelated memories."""
    c = Stub(repo, results=[_row("run", "proj.m.run", 1, 2)])
    await build(c, "something specific", cwd=str(repo))
    assert "run" not in c.recall_queries


@pytest.mark.asyncio
async def test_bound_project_scopes_recall_instead_of_filtering_after(repo):
    """With a binding, project scoping replaces the lexical gate -- a memory
    that does not name a shown symbol is still legitimate for this project."""
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"id": "1", "content": "the cache warms on first paint"}],
        memory_project="proj",
    )
    ctx = await build(c, "helper", cwd=str(repo))
    assert len(ctx.memories) == 1


@pytest.mark.asyncio
async def test_unbound_project_still_falls_back_to_the_lexical_gate(repo):
    """Without a binding, recall spans the whole store, so the gate must hold."""
    c = Stub(
        repo,
        results=[_row("helper", "proj.m.helper", 1, 2)],
        memories=[{"id": "1", "content": "the chrome extension debounces width"}],
    )
    ctx = await build(c, "helper", cwd=str(repo))
    assert ctx.memories == []


@pytest.mark.asyncio
async def test_duplicate_memories_across_probes_are_deduplicated(repo):
    c = Stub(
        repo,
        results=[
            _row("alpha", "proj.m.alpha", 1, 2),
            _row("beta", "proj.m.beta", 4, 5),
        ],
        memories=[{"id": "same", "content": "alpha and beta interact"}],
        memory_project="proj",
    )
    ctx = await build(c, "alpha beta", cwd=str(repo))
    assert len(ctx.memories) == 1


@pytest.mark.asyncio
async def test_project_scope_is_sent_with_search_all_not_instead_of_it(repo):
    """`project` is a filter over the searched set, not a scope selector.
    Sent alone it leaves the search on the default (empty) session and every
    query returns no_results."""
    seen = {}

    class Recorder(Stub):
        async def recall(self, query, limit=5, project=None, search_all=True):
            seen["project"] = project
            seen["search_all"] = search_all
            return []

    c = Recorder(
        repo, results=[_row("helper", "proj.m.helper", 1, 2)], memory_project="proj"
    )
    await build(c, "helper", cwd=str(repo))
    assert seen["project"] == "proj"
    assert seen["search_all"] is True


@pytest.mark.asyncio
async def test_an_lsp_edge_outweighs_a_heuristic_edge_of_higher_confidence():
    """Resolver reliability is not encoded in `confidence`.

    Measured against the live engine on this repo: LSP edges scored 0.88-0.97
    and heuristic edges 0.75-0.90, so the ranges overlap and a heuristic name
    match at 0.90 outweighed an LSP-resolved call at 0.88. Heuristic binding is
    what produces cross-module false edges -- `dict.items()` resolving to a
    module-level variable named `items` in an unrelated file -- so it must not
    be able to outrank a resolved call on confidence alone.
    """
    from marm_mcp_server.services.code_context.compose import _edges_from_trace

    payload = {
        "callees": [
            {"qualified_name": "p.m.resolved", "confidence": 0.88, "strategy": "lsp"},
            {
                "qualified_name": "p.other.guess",
                "confidence": 0.90,
                "strategy": "heuristic",
            },
        ]
    }
    edges = _edges_from_trace(payload, "p.m.origin")
    weight = {b: w for a, b, w in edges if a == "p.m.origin"}
    assert weight["p.m.resolved"] > weight["p.other.guess"]


@pytest.mark.asyncio
async def test_unresolved_edges_are_discarded_entirely():
    """An `unresolved` hop is the engine reporting it does not know. Carrying it
    as a weighted edge invents a call path that was never established."""
    from marm_mcp_server.services.code_context.compose import _edges_from_trace

    payload = {
        "callees": [
            {"qualified_name": "p.m.real", "confidence": 0.9, "strategy": "lsp"},
            {
                "qualified_name": "p.m.unknown",
                "confidence": 0.9,
                "strategy": "unresolved",
            },
        ]
    }
    targets = {b for a, b, _ in _edges_from_trace(payload, "p.m.origin")}
    assert "p.m.real" in targets
    assert "p.m.unknown" not in targets


@pytest.mark.asyncio
async def test_a_missing_strategy_is_treated_as_unreliable_not_trusted():
    """Older engines omit `strategy`. Absent evidence must not be read as LSP."""
    from marm_mcp_server.services.code_context.compose import _edges_from_trace

    payload = {
        "callees": [
            {"qualified_name": "p.m.known", "confidence": 0.9, "strategy": "lsp"},
            {"qualified_name": "p.m.nostrat", "confidence": 0.9},
        ]
    }
    weight = {
        b: w
        for a, b, w in _edges_from_trace(payload, "p.m.origin")
        if a == "p.m.origin"
    }
    assert weight["p.m.known"] > weight["p.m.nostrat"]


@pytest.mark.asyncio
async def test_a_test_does_not_outrank_the_implementation_it_exercises(repo):
    """`TEST_PENALTY` discounted seed mass only, which is half the problem.

    Penalising the restart mass reduces how much a test *radiates*, but a test
    still *receives* PageRank from the call graph, and the final ordering was
    not penalised at all. Observed live on this repo: asking "how does the
    ranking pipeline decide which symbols matter" returned two tests above
    `personalised_pagerank`, the function that answers the question.

    Tests are still surfaced -- their docstrings are often the best available
    description -- they just no longer displace the code they cover.
    """
    from marm_mcp_server.services.code_context.compose import (
        Symbol,
        _apply_test_penalty,
    )

    impl = Symbol(
        qualified_name="p.m.rank_it",
        name="rank_it",
        label="Function",
        file_path="m.py",
        start_line=1,
        end_line=9,
    )
    test = Symbol(
        qualified_name="p.tests.test_m.test_rank_it",
        name="test_rank_it",
        label="Function",
        file_path="tests/test_m.py",
        start_line=1,
        end_line=9,
    )
    from marm_mcp_server.services.code_context.compose import TEST_PENALTY

    impl.score, test.score = 0.10, 0.50  # the test leads before the penalty

    _apply_test_penalty([impl, test])

    # The implementation comes back on top at a realistic margin.
    assert impl.score > test.score
    # The discount lands on the final score, which is what ordering uses.
    assert test.score == 0.50 * TEST_PENALTY
    # Non-test scores are untouched, and the test is discounted, not discarded.
    assert impl.score == 0.10
    assert test.score > 0.0


def _sym(name, file_path):
    from marm_mcp_server.services.code_context.compose import Symbol

    return Symbol(
        qualified_name=f"p.m.{name}",
        name=name,
        label="Function",
        file_path=file_path,
        start_line=1,
        end_line=9,
    )


@pytest.mark.asyncio
async def test_one_ordinary_english_word_is_not_enough_to_admit_a_memory():
    """The leak this closes, observed live.

    Asking about the ranking pipeline surfaced a memory reading "...adds
    additional licenses to resolve the 4 incompatible license failures" —
    a different repository entirely. It passed because `resolve` is a symbol in
    project.py and clears `is_distinctive`, and the memory used the word as an
    ordinary verb.

    A bare dictionary word is weak evidence however distinctive it looks as an
    identifier. `resolve`, `search`, `rank` and `compose` are all symbols here
    and all ordinary English.
    """
    from marm_mcp_server.services.code_context.compose import _relevant_memories

    symbols = [
        _sym("resolve", "marm_ctx/project.py"),
        _sym("personalised_pagerank", "marm_ctx/rank.py"),
    ]
    rows = [
        {
            "content": "Committed expanded license allowlist to fix dependency "
            "review. New commit adds licenses to resolve the 4 "
            "incompatible license failures."
        }
    ]
    assert _relevant_memories(rows, symbols, {"root_path": "/x/MARM-Stack"}) == []


@pytest.mark.asyncio
async def test_a_structural_anchor_still_admits_a_memory_on_one_hit():
    """An identifier-shaped name or a filename does not occur in ordinary prose,
    so one hit is enough. Tightening must not silence real memories."""
    from marm_mcp_server.services.code_context.compose import _relevant_memories

    symbols = [_sym("personalised_pagerank", "marm_ctx/rank.py")]
    for text in (
        "reworked personalised_pagerank to damp dangling mass",
        "rank.py now scales edge weight by resolver strategy",
    ):
        kept = _relevant_memories(
            [{"content": text}], symbols, {"root_path": "/x/MARM-Stack"}
        )
        assert len(kept) == 1, text


@pytest.mark.asyncio
async def test_two_ordinary_words_together_are_enough():
    """Weak evidence accumulates. Two unrelated common symbols co-occurring is
    no longer a coincidence worth discarding."""
    from marm_mcp_server.services.code_context.compose import _relevant_memories

    symbols = [
        _sym("resolve", "marm_ctx/project.py"),
        _sym("compose", "marm_ctx/compose.py"),
    ]
    rows = [{"content": "the resolve step runs before compose in the pipeline"}]
    assert len(_relevant_memories(rows, symbols, {"root_path": "/x/MARM-Stack"})) == 1


@pytest.mark.asyncio
async def test_the_project_name_counts_as_a_structural_anchor():
    """Naming the repository is unambiguous evidence about which repo it means."""
    from marm_mcp_server.services.code_context.compose import _relevant_memories

    symbols = [_sym("resolve", "marm_ctx/project.py")]
    rows = [{"content": "marm-stack now pins its ruff rule set in ruff.toml"}]
    assert len(_relevant_memories(rows, symbols, {"root_path": "/x/MARM-Stack"})) == 1
