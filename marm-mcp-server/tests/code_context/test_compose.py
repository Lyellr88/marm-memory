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
    # Keyed by the QUALIFIED name, because that is what build() traces. Keying it
    # by the bare tail made the stub return {} -- no promotion happened at all,
    # and the assertion below passed only because `central` was already a seed.
    trace = {
        "proj.m.caller": {
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
    assert "central" in [s.name for s in ctx.symbols]

    # Membership alone proves nothing -- `central` is already a seed, so it is
    # present whether or not the call graph was consulted. The promotion is the
    # change in relative score, so the test compares the two rankings directly.
    baseline = await build(
        Stub(repo, results=results, trace={}), "caller", cwd=str(repo)
    )

    def ratio(context):
        by_name = {s.name: s.score for s in context.symbols}
        return by_name["central"] / by_name["caller"]

    # Measured: 0.50 on search order alone, ~0.95 once the callee edge is used.
    assert ratio(ctx) > ratio(baseline) * 1.5


@pytest.mark.asyncio
async def test_budget_is_respected(repo):
    (repo / "m.py").write_text("\n".join(f"line {i}" for i in range(400)))
    c = Stub(repo, results=[_row("big", "proj.m.big", 1, 400)])
    ctx = await build(c, "big", cwd=str(repo), budget=50)
    # The contract is a CHARACTER budget. Before the per-snippet clamp this could
    # only be asserted loosely, because one 60-line snippet was appended whole
    # before `spent` was re-checked.
    assert sum(len(s.source) for s in ctx.symbols) <= 50


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
async def test_a_failed_trace_is_reported_not_silently_dropped(repo):
    """A trace failure arrives as `{"status": "error"}`, not as an exception.

    An errored payload carries no edges, which is indistinguishable from "this
    symbol calls nothing" -- so an engine outage produced a source-only
    composition that looked complete, with no graph nodes and no warning. It is
    unavailability, and the result has to say so.
    """

    class Broken(Stub):
        def trace(self, project, symbol, depth=2, direction="both"):
            return {"status": "error", "message": "engine gone"}

    c = Broken(repo, results=[_row("helper", "proj.m.helper", 1, 2)])
    ctx = await build(c, "helper", cwd=str(repo))

    assert ctx.symbols, "the seeds still answer; only the call graph is missing"
    assert ctx.graph_nodes == 0
    assert any("call graph unavailable" in n for n in ctx.notes), (
        f"a failed trace must be reported, not presented as an empty "
        f"neighbourhood; notes were {ctx.notes}"
    )


@pytest.mark.asyncio
async def test_a_partial_trace_failure_says_how_many(repo):
    """One bad symbol must not be reported as a whole-graph outage, or vice versa."""

    class Half(Stub):
        def trace(self, project, symbol, depth=2, direction="both"):
            if symbol == "proj.m.good":
                return {
                    "callees": [
                        {"qualified_name": "proj.m.other", "name": "other", "hop": 1}
                    ]
                }
            return {"status": "error", "message": "engine gone"}

    c = Half(
        repo,
        results=[
            _row("good", "proj.m.good", 1, 2),
            _row("bad", "proj.m.bad", 3, 4),
        ],
    )
    ctx = await build(c, "good bad", cwd=str(repo))

    assert ctx.graph_nodes > 0, "the healthy symbol still contributes edges"
    assert any("call graph unavailable for 1 of" in n for n in ctx.notes), ctx.notes


@pytest.mark.asyncio
async def test_the_unavailable_note_counts_only_trace_candidates(repo):
    """The denominator is what was expanded, not what ended up in the map.

    A successful trace adds graph-derived symbols, so measuring after the loop
    counts symbols that were never candidates for expansion.
    """

    class Mixed(Stub):
        def trace(self, project, symbol, depth=2, direction="both"):
            if symbol == "proj.m.good":
                return {
                    "callees": [
                        {"qualified_name": f"proj.m.extra{i}", "name": f"extra{i}"}
                        for i in range(5)
                    ]
                }
            return {"status": "error", "message": "engine gone"}

    c = Mixed(
        repo,
        results=[
            _row("good", "proj.m.good", 1, 2),
            _row("bad", "proj.m.bad", 3, 4),
        ],
    )
    ctx = await build(c, "good bad", cwd=str(repo))
    note = next(n for n in ctx.notes if "call graph unavailable" in n)
    assert note.endswith("of 2 expanded symbols"), (
        f"five symbols arrived via trace and must not inflate the denominator: {note}"
    )


@pytest.mark.asyncio
async def test_a_graph_outage_during_backfill_still_returns_a_composition(repo):
    """The backfill search is cosmetic; losing it must not fail the request.

    Every other graph call in build() degrades. This one resolves a file and
    line for a symbol the ranking already has, so an engine that dies after
    seeding should cost the line numbers, not the whole composition.
    """
    from marm_mcp_server.services.code_context.backend import GraphUnavailable

    class DiesLate(Stub):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._seeded = False

        def search(self, project, query, limit=25, semantic=None):
            if self._seeded:
                raise GraphUnavailable("engine gone")
            self._seeded = True
            return self._results

        def trace(self, project, symbol, depth=2, direction="both"):
            return {
                "callees": [
                    {"qualified_name": "proj.m.orphan", "name": "orphan", "hop": 1}
                ]
            }

    c = DiesLate(repo, results=[_row("caller", "proj.m.caller", 1, 2)])
    ctx = await build(c, "caller", cwd=str(repo))
    assert ctx.symbols, "the composition must survive a backfill outage"


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


def test_snippet_read_refuses_a_path_outside_the_project_root(tmp_path):
    """The engine reports file_path; this process opens it and returns the text
    to the MCP caller, so containment is checked rather than assumed.

    os.path.join returns an absolute second argument unchanged, and does nothing
    about `..` or a symlink pointing out of the tree.
    """
    from marm_mcp_server.services.code_context.snippets import read

    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "ok.py").write_text("line one\nline two\n")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text("SECRET\n")

    assert read(str(root), "pkg/ok.py", 1, 2)[0] == "line one\nline two"
    assert read(str(root), str(outside / "secret.txt"), 1, 1)[0] == ""
    assert read(str(root), "../elsewhere/secret.txt", 1, 1)[0] == ""

    # Creating a symlink needs a privilege most Windows setups do not grant, and
    # an unprivileged failure here aborts the test BEFORE the absolute and
    # traversal assertions above -- losing coverage that has nothing to do with
    # symlinks. Only this last check is conditional.
    try:
        (root / "link.txt").symlink_to(outside / "secret.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink on this platform: {exc}")
    assert read(str(root), "link.txt", 1, 1)[0] == ""


@pytest.mark.asyncio
async def test_a_dead_graph_is_not_an_empty_result(repo):
    """`do_lookup` is wrapped in @safe, so a failure arrives as a payload rather
    than an exception. Reading it as zero results would report a successful
    composition with no symbols -- indistinguishable from a genuine miss."""
    from marm_mcp_server.services.code_context.backend import (
        GraphUnavailable,
        LocalBackend,
    )

    backend = LocalBackend.__new__(LocalBackend)
    backend._client = lambda: None  # type: ignore[method-assign]

    import marm_graph.core.tool_router as R

    original = R.do_lookup
    R.do_lookup = lambda *_a, **_k: {"status": "error", "error": "engine gone"}
    try:
        with pytest.raises(GraphUnavailable):
            backend.search("proj", "anything")
    finally:
        R.do_lookup = original


@pytest.mark.asyncio
async def test_a_missed_qualified_trace_is_not_retried_by_bare_name(repo):
    """Retrying with the bare tail can resolve a DIFFERENT symbol that owns that
    name elsewhere and splice its call graph into the ranking. Skipping loses
    edges; guessing invents them."""
    traced: list[str] = []

    class _Tracer(Stub):
        def trace(self, project, symbol, depth=2, direction="both"):
            traced.append(symbol)
            return {"status": "not_found"}

    results = [_row("handler", "proj.a.handler", 1, 2)]
    await build(_Tracer(repo, results=results), "handler", cwd=str(repo))

    assert traced == ["proj.a.handler"], f"unexpected trace calls: {traced}"


@pytest.mark.asyncio
async def test_a_traced_caller_ranked_past_the_top_dozen_is_still_shown(tmp_path):
    """Asking "what calls X" is answered by X's callers, and a popular X has
    more of them than a fixed backfill window. A caller left without a file is
    never emitted, while seeded symbols ranked far below it are."""
    names = [f"c{i}" for i in range(16)]
    (tmp_path / "m.py").write_text(
        "def target():\n    return 1\n\n"
        + "".join(f"def {n}():\n    return target()\n\n" for n in names)
    )
    rows = {
        n: _row(n, f"proj.m.{n}", 4 + 3 * i, 5 + 3 * i) for i, n in enumerate(names)
    }
    trace = {
        "proj.m.target": {
            "callers": [
                {"qualified_name": f"proj.m.{n}", "name": n, "hop": 1} for n in names
            ]
        }
    }

    class Resolving(Stub):
        def search(self, project, query, limit=25, semantic=None):
            self.searches.append(query)
            if query in rows:
                return [rows[query]]
            return self._results

    c = Resolving(
        tmp_path, results=[_row("target", "proj.m.target", 1, 2)], trace=trace
    )
    ctx = await build(c, "target", cwd=str(tmp_path))

    shown = {s.name for s in ctx.symbols}
    assert set(names) <= shown, sorted(set(names) - shown)


@pytest.mark.asyncio
async def test_backfill_finds_a_common_name_behind_its_namesakes(repo):
    """A bare-name search for `request` returns every `request` in the
    project; the traced one is rarely among the first three."""
    trace = {
        "proj.m.helper": {
            "callers": [{"qualified_name": "proj.m.caller", "name": "caller", "hop": 1}]
        }
    }
    namesakes = [_row("caller", f"proj.other{i}.caller") for i in range(4)]

    class Crowded(Stub):
        def search(self, project, query, limit=25, semantic=None):
            self.searches.append(query)
            if query == "caller":
                return [*namesakes, _row("caller", "proj.m.caller", 7, 8)][:limit]
            return self._results

    c = Crowded(repo, results=[_row("helper", "proj.m.helper", 1, 2)], trace=trace)
    ctx = await build(c, "helper", cwd=str(repo))

    caller = next((s for s in ctx.symbols if s.qualified_name == "proj.m.caller"), None)
    assert caller is not None
    assert (caller.start_line, caller.end_line) == (7, 8)


def _hub(tmp_path):
    """`target` calls six helpers and is called by one entry point."""
    helpers = [f"h{i}" for i in range(6)]
    (tmp_path / "m.py").write_text(
        "def target():\n"
        + "".join(f"    {h}()\n" for h in helpers)
        + "\ndef entry():\n    target()\n\n"
        + "".join(f"def {h}():\n    pass\n\n" for h in helpers)
    )
    trace = {
        "proj.m.target": {
            "callees": [
                {"qualified_name": f"proj.m.{h}", "name": h, "hop": 1} for h in helpers
            ],
            "callers": [{"qualified_name": "proj.m.entry", "name": "entry", "hop": 1}],
        }
    }
    rows = {
        h: _row(h, f"proj.m.{h}", 12 + 3 * i, 13 + 3 * i) for i, h in enumerate(helpers)
    }
    rows["entry"] = _row("entry", "proj.m.entry", 9, 10)

    class Resolving(Stub):
        def search(self, project, query, limit=25, semantic=None):
            self.searches.append(query)
            return [rows[query]] if query in rows else self._results

    return Resolving(
        tmp_path, results=[_row("target", "proj.m.target", 1, 7)], trace=trace
    )


@pytest.mark.asyncio
async def test_asking_what_calls_a_symbol_ranks_its_callers_first(tmp_path):
    """A caller and a callee of the seed tie in the call graph; the question
    is what breaks the tie."""
    ctx = await build(_hub(tmp_path), "what calls target", cwd=str(tmp_path))
    names = [s.name for s in ctx.symbols]
    assert names.index("entry") < min(names.index(f"h{i}") for i in range(6)), names


@pytest.mark.asyncio
async def test_asking_how_a_symbol_works_does_not_promote_its_callers(tmp_path):
    """Without the question, the call graph decides, and it weights what the
    seed calls above what calls the seed."""
    ctx = await build(_hub(tmp_path), "how does target work", cwd=str(tmp_path))
    names = [s.name for s in ctx.symbols]
    assert names.index("entry") > max(names.index(f"h{i}") for i in range(6)), names
