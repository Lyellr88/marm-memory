import pytest

from marm_mcp_server.services.analyst.packet import build_packet
from marm_mcp_server.services.analyst.verify import extract_citations, verify
from marm_mcp_server.services.code_context.compose import Context, Symbol


@pytest.fixture
def packet():
    return build_packet(
        Context(
            project={"name": "demo"},
            task="how does apply work",
            symbols=[
                Symbol(
                    "pkg.svc.apply",
                    "apply",
                    "Function",
                    "pkg/svc.py",
                    10,
                    40,
                    source="def apply():\n    claim()\n    write_row()\n",
                ),
                Symbol(
                    "pkg.svc.claim",
                    "claim",
                    "Function",
                    "pkg/svc.py",
                    50,
                    60,
                    source="def claim():\n    pass\n",
                ),
            ],
            memories=[{"id": "m-1", "content": "apply claims before writing"}],
            links=[{"qualified_name": "pkg.svc.apply", "entity_name": "apply"}],
            graph_edges=[("pkg.svc.apply", "pkg.svc.claim", 1.0)],
        )
    )


def test_fully_supported_answer_is_verified(packet):
    v = verify(
        "`apply` calls `claim` before it writes [S1] [S2]. "
        "Memory agrees that apply claims first [M1].",
        packet,
    )
    assert v.state == "verified", v
    assert v.score == 1.0


def test_no_citations_is_uncertain_not_rejected(packet):
    """Missing evidence is not counter-evidence."""
    v = verify("apply calls claim before it writes.", packet)
    assert v.state == "uncertain"
    assert v.citation_coverage == 0.0
    assert v.hard_failures == ()


def test_invented_handle_is_a_hard_failure(packet):
    v = verify("apply calls claim [S1] [S9].", packet)
    assert v.state == "rejected"
    assert any("S9" in f for f in v.hard_failures)


def test_invented_symbol_name_is_a_hard_failure(packet):
    v = verify("apply delegates to [persist_everything].", packet)
    assert v.state == "rejected"


def test_bare_symbol_names_resolve_like_handles(packet):
    cited, unresolved = extract_citations("see [apply] and [`claim`]", packet)
    assert [c.handle for c in cited] == ["S1", "S2"]
    assert unresolved == []


def test_each_name_in_a_multi_name_bracket_is_resolved(packet):
    cited, unresolved = extract_citations("see [S1, `claim`; M1]", packet)
    assert [c.handle for c in cited] == ["S1", "S2", "M1"]
    assert unresolved == []


def test_an_invented_name_cannot_hide_beside_a_real_one(packet):
    v = verify("apply claims first [apply, persist_everything].", packet)
    assert v.state == "rejected"
    assert any("persist_everything" in f for f in v.hard_failures)


def test_non_citation_brackets_are_ignored(packet):
    text = (
        "apply claims first [S1]. See [setup_guide](https://x.y) and [1]. "
        "- [ ] todo, pass [optional] args."
    )
    _, unresolved = extract_citations(text, packet)
    assert unresolved == []
    assert verify(text, packet).hard_failures == ()


def test_code_span_not_in_packet_lowers_span_support(packet):
    v = verify("apply calls `commit_transaction` [S1].", packet)
    assert v.source_span_support < 1.0
    assert v.state == "uncertain"


def test_line_reference_outside_the_cited_span_fails_support(packet):
    ok = verify("It starts at pkg/svc.py:12 [S1].", packet)
    bad = verify("It starts at pkg/svc.py:400 [S1].", packet)
    assert ok.source_span_support == 1.0
    assert bad.source_span_support < 1.0


def test_call_claim_without_an_edge_is_inconsistent(packet):
    v = verify("claim [S2] calls apply [S1].", packet)
    assert v.graph_memory_consistency < 1.0


def test_memory_cited_with_unrelated_symbol_is_inconsistent(packet):
    v = verify("Memory says claim is idempotent [M1] [S2].", packet)
    assert v.graph_memory_consistency < 1.0


def test_score_is_the_minimum_not_the_mean(packet):
    v = verify("apply calls `commit_transaction` [S1]. claim is small [S2].", packet)
    assert v.score == min(
        v.citation_coverage, v.source_span_support, v.graph_memory_consistency
    )


def test_a_low_score_never_rejects_on_its_own(packet):
    """Only a hard failure rejects; a weak answer is uncertain."""
    v = verify("apply writes `nope_a` and `nope_b` and `nope_c`.", packet)
    assert v.score < 0.5
    assert v.state == "uncertain"


def test_abstention_is_uncertain_not_rejected(packet):
    v = verify(
        "The context does not show where the retry budget is configured.", packet
    )
    assert v.abstained is True
    assert v.state == "uncertain"


def test_public_shape(packet):
    pub = verify("apply calls claim [S1] [S2].", packet).to_public()
    assert set(pub) == {
        "state",
        "score",
        "citation_coverage",
        "source_span_support",
        "graph_memory_consistency",
        "claims",
        "cited_claims",
        "failures",
        "hard_failures",
        "abstained",
    }


def test_markdown_scaffolding_is_not_a_claim(packet):
    """`- [ ] todo` is three tokens and no statement; counting it as an
    uncited claim would mark a fully cited answer unverified."""
    v = verify("apply claims first [S1].\n- [ ] todo\nfootnote [1]", packet)
    assert v.claims == 1
    assert v.state == "verified"


# --- cases taken from real answers ---------------------------------------------
# Four of eleven non-verified answers were correct and fully cited; each was
# marked uncertain for a list lead-in such as "This process involves:".


@pytest.mark.parametrize(
    "answer",
    [
        "apply claims the row first [S1]. This process involves:\n"
        "*   **Ordering:** it writes only after claiming [S1].",
        "apply claims the row [S1] using the following logic:\n"
        "1.  **Claim:** it calls claim first [S1].",
        "When the claim fails, apply stops [S1].\n\nDepending on the entry point:\n"
        "*   apply returns early [S1].",
        "apply sanitises the row [S1]. It performs the following transformations:\n"
        "*   **Claim:** it calls claim [S1].",
    ],
)
def test_a_list_lead_in_is_not_an_uncited_claim(packet, answer):
    v = verify(answer, packet)
    assert "uncited claims" not in v.failures, v.failures
    assert v.citation_coverage == 1.0


def test_a_colon_inside_a_sentence_is_still_a_claim(packet):
    v = verify("apply does two things: it claims and it writes.", packet)
    assert v.claims == 1
    assert "uncited claims" in v.failures


def test_an_uncited_statement_still_counts_after_a_lead_in(packet):
    v = verify(
        "apply works like this:\n* it claims the row first [S1].\n* it retries forever.",
        packet,
    )
    assert "uncited claims" in v.failures


def test_one_citation_closing_a_bullet_covers_the_bullet(packet):
    """The real shape: a bullet of two sentences, cited once at its end."""
    answer = (
        "2.  **Claim:** apply looks at the row first. If it is free, apply "
        "claims it before writing [S1]."
    )
    v = verify(answer, packet)
    assert "uncited claims" not in v.failures, v.failures


def test_a_citation_does_not_reach_back_across_lines(packet):
    v = verify("apply retries forever.\napply claims the row first [S1].", packet)
    assert "uncited claims" in v.failures


def test_an_abstention_is_not_folded_into_the_cited_claim_after_it(packet):
    v = verify(
        "The packet does not show the retry policy. apply claims first [S1].", packet
    )
    assert v.state == "verified", (v.state, v.failures)
    assert v.claims == 1


@pytest.fixture
def bind_packet():
    return build_packet(
        Context(
            project={"name": "demo"},
            task="how are bindings created",
            symbols=[
                Symbol(
                    "pkg.bind.auto_bind",
                    "auto_bind",
                    "Function",
                    "pkg/bind.py",
                    1,
                    3,
                    source="def auto_bind(self, graph):\n    store.insert(graph)\n",
                ),
            ],
        )
    )


@pytest.mark.parametrize("span", ["auto_bind()", "store.insert()"])
def test_an_empty_call_names_the_function_it_calls(bind_packet, span):
    """`name()` is how prose writes a function; the source never spells it
    with empty parentheses once the function takes arguments."""
    v = verify(f"Binding uses `{span}` [S1].", bind_packet)
    assert v.source_span_support == 1.0, v.failures


@pytest.mark.parametrize("span", ["ghost()", "auto_bind(force=True)", "store.remove()"])
def test_a_call_the_packet_does_not_hold_still_fails(bind_packet, span):
    v = verify(f"Bindings are created by `{span}` [S1].", bind_packet)
    assert v.source_span_support == 0.0


@pytest.mark.parametrize(
    "text",
    [
        "There is no direct evidence that [S1] calls [S2].",
        "There is no clear evidence that [S2] calls [S1].",
        "The packet does not directly show that [S2] calls [S1].",
        "The context does not clearly show whether [S2] invokes [S1].",
    ],
)
def test_a_qualified_abstention_about_a_call_is_not_a_call_claim(packet, text):
    """Saying the evidence is missing asserts nothing, so there is no edge to
    check and nothing to call inconsistent."""
    v = verify(text, packet)
    assert v.abstained is True, v
    assert not any("call edge" in f for f in v.failures), v.failures
    assert v.state == "uncertain"


def test_a_cited_abstention_does_not_hide_the_uncited_claim_before_it(packet):
    """Folding the claim into the abstention after it would drop it from the
    count along with the abstention."""
    v = verify(
        "apply retries forever. There is no direct evidence that [S1] calls [S2].",
        packet,
    )
    assert v.claims == 1
    assert "uncited claims" in v.failures


def test_a_negated_call_agrees_with_a_missing_edge(packet):
    """`claim` does not call `apply`, and the packet holds no such edge."""
    v = verify("claim [S2] does not call apply [S1].", packet)
    assert v.graph_memory_consistency == 1.0, v.failures


def test_a_negated_call_contradicts_an_edge_the_packet_holds(packet):
    v = verify("apply [S1] never calls claim [S2].", packet)
    assert v.graph_memory_consistency < 1.0
    assert any("call edge" in f for f in v.failures), v.failures


@pytest.mark.parametrize(
    "text",
    [
        "apply claims the row first [S1]. It does not include any retry logic.",
        "apply claims the row first [S1]. The function does not show a warning.",
    ],
)
def test_a_negative_claim_about_the_code_is_still_a_claim(packet, text):
    """Only a statement about the evidence is an abstention; one about the code,
    however negative, needs a citation like any other claim."""
    v = verify(text, packet)
    assert v.state != "verified", v
    assert "uncited claims" in v.failures


def test_a_packet_id_covers_everything_the_model_is_shown():
    def packet(label, truncated, name="a"):
        return build_packet(
            Context(
                project={"name": "demo"},
                task="how",
                symbols=[
                    Symbol(
                        "pkg.a",
                        name,
                        label,
                        "pkg/a.py",
                        1,
                        2,
                        source="def a(): pass",
                        truncated=truncated,
                    )
                ],
            )
        )

    base = packet("Function", False).packet_id
    assert packet("Method", False).packet_id != base
    assert packet("Function", True).packet_id != base
    assert packet("Function", False, name="alias").packet_id != base


# --- claim words must come from the evidence they cite ----------------------

from marm_mcp_server.services.analyst.verify import (  # noqa: E402
    check_item,
    disagreements,
    unsupported_terms,
)


@pytest.fixture
def apply_packet():
    """The maintainer's regression: a real `apply` that deletes nothing."""
    return build_packet(
        Context(
            project={"name": "demo"},
            task="what does apply do",
            symbols=[
                Symbol(
                    "pkg.apply",
                    "apply",
                    "Function",
                    "pkg/a.py",
                    1,
                    1,
                    source="def apply(): return 1",
                )
            ],
        )
    )


def test_a_cited_claim_the_source_does_not_support_is_not_verified(apply_packet):
    v = verify("apply deletes every memory [S1].", apply_packet)
    assert v.state != "verified"
    assert any("deletes" in f for f in v.failures)


def test_the_same_claim_as_a_structured_fact_is_not_verified(apply_packet):
    check = check_item(
        "facts",
        text="apply deletes every memory",
        packet=apply_packet,
        cites=("S1",),
        quote="def apply(): return 1",
    )
    assert check.state == "uncertain"
    assert check.support == "none"


def test_a_supported_structured_fact_is_verified_by_its_quote(apply_packet):
    check = check_item(
        "facts",
        text="apply returns 1",
        packet=apply_packet,
        cites=("S1",),
        quote="def apply(): return 1",
    )
    assert (check.state, check.support) == ("verified", "quote")


def test_a_quote_from_an_uncited_item_does_not_count(packet):
    check = check_item(
        "facts", text="claim passes", packet=packet, cites=("S2",), quote="write_row()"
    )
    assert check.state == "uncertain", "write_row() is in S1, not the cited S2"


def test_an_invented_handle_rejects_an_item(packet):
    check = check_item("summary", text="apply works", packet=packet, cites=("S9",))
    assert check.state == "rejected"
    assert check.hard_failures == ("reference not in packet: [S9]",)


def test_a_call_relation_needs_the_packet_edge(packet):
    ok = check_item(
        "relations",
        text="apply calls claim",
        packet=packet,
        kind="calls",
        source="S1",
        target="S2",
    )
    backwards = check_item(
        "relations",
        text="claim calls apply",
        packet=packet,
        kind="calls",
        source="S2",
        target="S1",
    )
    assert (ok.state, ok.support) == ("verified", "edge")
    assert backwards.state == "uncertain"


def test_a_memory_relation_needs_a_link_or_a_mention(packet):
    check = check_item(
        "relations",
        text="M1 is about apply",
        packet=packet,
        kind="memory_about",
        source="M1",
        target="S1",
    )
    assert (check.state, check.support) == ("verified", "link")


def test_gaps_and_next_steps_are_never_verified_facts(packet):
    gap = check_item("gaps", text="the writer is not shown", packet=packet)
    step = check_item("next_steps", text="read claim", packet=packet, cites=("S2",))
    assert gap.state == "missing" and step.state == "proposal"


def test_generic_code_words_need_no_evidence():
    assert unsupported_terms("the function returns a value", "x") == []


def test_stacked_suffixes_meet_their_stem():
    assert unsupported_terms("bindings", "def bind(): pass") == []


# --- code-memory disagreement, found without a model ------------------------


def _mem_packet(memory, edges):
    return build_packet(
        Context(
            project={"name": "demo"},
            task="t",
            symbols=[
                Symbol("pkg.apply", "apply", "Function", "a.py", 1, 2, source="x"),
                Symbol("pkg.claim", "claim", "Function", "a.py", 3, 4, source="y"),
            ],
            memories=[{"id": "m1", "content": memory}],
            graph_edges=edges,
        )
    )


def test_a_memory_denying_an_edge_the_graph_has_is_contradicted():
    p = _mem_packet("apply does not call claim.", [("pkg.apply", "pkg.claim", 1.0)])
    (d,) = disagreements(p)
    assert (d.severity, d.memory, d.source, d.target) == (
        "contradicted",
        "M1",
        "S1",
        "S2",
    )


def test_a_memory_asserting_an_edge_the_packet_lacks_is_unconfirmed():
    p = _mem_packet("apply calls claim before writing.", [])
    (d,) = disagreements(p)
    assert d.severity == "unconfirmed" and d.graph == "no edge"


def test_a_memory_that_agrees_with_the_graph_is_no_disagreement():
    p = _mem_packet("apply calls claim.", [("pkg.apply", "pkg.claim", 1.0)])
    assert disagreements(p) == []


# --- found by running an 8B model through the matrix ------------------------


def test_quoting_the_packets_own_locator_is_supported(packet):
    """The packet renders `path:start-end`; quoting it back quotes the packet."""
    v = verify("`apply` is at `pkg/svc.py:10-40` [S1].", packet)
    assert not any("pkg/svc.py:10-40" in f for f in v.failures), v.failures


def test_a_claim_with_nothing_checkable_is_not_verified(packet):
    """ "No, it does not." cited S1 and verified, because nothing could fail."""
    assert verify("No, it does not [S1].", packet).state == "uncertain"
    check = check_item("summary", text="No, it does not.", packet=packet, cites=("S1",))
    assert check.state == "uncertain"


def test_a_verbatim_memory_quote_cannot_verify_a_call_the_graph_contradicts(packet):
    """A quote proves what the memory says, not that the code agrees."""
    mem_packet = build_packet(
        Context(
            project={"name": "demo"},
            task="does apply call claim",
            symbols=[
                Symbol("pkg.apply", "apply", "Function", "a.py", 1, 2, source="x"),
                Symbol("pkg.claim", "claim", "Function", "a.py", 3, 4, source="y"),
            ],
            memories=[{"id": "m1", "content": "apply does not call claim."}],
            graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
        )
    )
    check = check_item(
        "facts",
        text="apply does not call claim",
        packet=mem_packet,
        cites=("M1",),
        quote="apply does not call claim.",
    )
    assert check.state == "uncertain"
    assert any("contradicts" in f for f in check.failures)


def test_a_quoted_memory_statement_is_reported_not_claimed(packet):
    """`M1 says "apply does not call claim"` reports the memory; it does not
    deny the edge itself."""
    v = verify('Memory [M1] says "apply does not call claim" [S1] [S2].', packet)
    assert not any("contradicts" in f for f in v.failures), v.failures


def test_ing_and_ed_forms_meet_their_e_stem():
    assert unsupported_terms("writing", "def write(): pass") == []
    assert unsupported_terms("initialized", "def initialize(): pass") == []


# --- second review round -----------------------------------------------------


def test_a_real_edge_does_not_verify_what_its_text_claims(packet):
    """A packet edge proves the call, not the words written beside it."""
    check = check_item(
        "relations",
        text="apply deletes every memory",
        packet=packet,
        kind="calls",
        source="S1",
        target="S2",
    )
    assert check.state == "uncertain"
    assert any("deletes" in f for f in check.failures)


def test_a_quote_must_match_character_for_character(apply_packet):
    check = check_item(
        "facts",
        text="apply returns 1",
        packet=apply_packet,
        cites=("S1",),
        quote="def apply():  return 1",
    )
    assert check.state == "uncertain"


def test_a_subscript_inside_code_is_not_a_citation(packet):
    """`cache[row_id]` is quoted code, not an invented reference."""
    v = verify("apply reads `cache[row_id]` [S1].", packet)
    assert v.state != "rejected"
    assert extract_citations("see `d[some_key]`", packet)[1] == []


def test_a_backticked_citation_still_counts(packet):
    cites, unresolved = extract_citations("apply does it [`claim`].", packet)
    assert [c.name for c in cites] == ["claim"] and unresolved == []


# --- negation: every word supported, the meaning inverted --------------------


def _commented(source):
    return build_packet(
        Context(
            project={"name": "demo"},
            task="what does sweep do",
            symbols=[
                Symbol("pkg.sweep", "sweep", "Function", "a.py", 1, 5, source=source),
            ],
            memories=[{"id": "m1", "content": "sweep never deletes every memory row."}],
        )
    )


NEGATED = "def sweep():\n    # never deletes every memory row\n    return scan()\n"


def test_a_claim_the_cited_comment_negates_is_not_verified():
    packet = _commented(NEGATED)
    v = verify("sweep deletes every memory row [S1].", packet)
    assert v.state != "verified"
    assert any("opposite" in f for f in v.failures)


def test_a_structured_fact_the_evidence_negates_is_not_verified():
    check = check_item(
        "facts",
        text="sweep deletes every memory row",
        packet=_commented(NEGATED),
        cites=("M1",),
        quote="sweep never deletes every memory row.",
    )
    assert check.state == "uncertain"


def test_a_claim_that_keeps_the_negation_is_verified():
    v = verify("sweep never deletes every memory row [S1].", _commented(NEGATED))
    assert v.state == "verified", v.failures


def test_a_negation_elsewhere_in_the_sentence_does_not_count(packet):
    """ "marks the row applied so a caller cannot write it" negates the
    writing, not the marking."""
    source = (
        'def mark():\n    """Mark the row applied so a second caller cannot write '
        'it again."""\n'
    )
    p = _commented(source)
    v = verify("mark marks the row applied [S1].", p)
    assert not any("opposite" in f for f in v.failures), v.failures


def test_code_is_not_read_for_negation():
    """`if not rows` is an operator, not a denial."""
    p = _commented(
        "def sweep(rows):\n    return None if not rows else delete_rows(rows)\n"
    )
    v = verify("sweep deletes rows [S1].", p)
    assert not any("opposite" in f for f in v.failures), v.failures


def test_a_negation_on_the_previous_comment_line_still_governs():
    """A comment sentence wraps: `# must never` / `# write the row directly`."""
    p = _commented(
        "def sweep():\n    # Callers must never\n    # write the row directly.\n"
        "    return 1\n"
    )
    v = verify("sweep writes the row directly [S1].", p)
    assert v.state != "verified"
    assert any("opposite" in f for f in v.failures)


def test_a_wrapped_docstring_is_one_block_too():
    p = _commented(
        'def sweep():\n    """Callers must never\n    write the row directly."""\n'
    )
    assert any(
        "opposite" in f
        for f in verify("sweep writes the row directly [S1].", p).failures
    )


def test_a_relation_is_checked_by_its_edge_even_with_empty_text(packet):
    """The edge is a relation's checkable content; placeholder text asserts
    nothing that could be false."""
    check = check_item(
        "relations", text="...", packet=packet, kind="calls", source="S1", target="S2"
    )
    assert (check.state, check.support) == ("verified", "edge")


def test_negated_relation_text_contradicts_its_own_edge():
    """ "never calls" beside a real S1 -> S2 edge denies the relation it
    labels, even when `never` appears elsewhere in the cited prose."""
    p = build_packet(
        Context(
            project={"name": "demo"},
            task="t",
            symbols=[
                Symbol(
                    "pkg.apply",
                    "apply",
                    "Function",
                    "a.py",
                    1,
                    3,
                    source="def apply():\n    # never retries\n    claim()\n",
                ),
                Symbol("pkg.claim", "claim", "Function", "a.py", 4, 5, source="x"),
            ],
            graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
        )
    )
    denied = check_item(
        "relations",
        text="never calls",
        packet=p,
        kind="calls",
        source="S1",
        target="S2",
    )
    plain = check_item(
        "relations", text="calls", packet=p, kind="calls", source="S1", target="S2"
    )
    assert denied.state == "uncertain"
    assert plain.state == "verified"


@pytest.mark.parametrize(
    "text",
    [
        "apply claims first [S1]. apply deletes every row, and there is no "
        "evidence it retries.",
        "apply claims first [S1]. The packet does not show retries, but apply "
        "deletes every row.",
        "apply claims first [S1]. apply deletes every row; the packet does not "
        "show retries.",
    ],
)
def test_an_abstention_clause_does_not_exempt_the_claim_beside_it(packet, text):
    v = verify(text, packet)
    assert "uncited claims" in v.failures, v.failures
    assert v.state != "verified"


def test_an_abstention_clause_beside_a_cited_claim_still_verifies(packet):
    v = verify("apply claims first [S1], but the packet does not show retries.", packet)
    assert v.state == "verified", (v.state, v.failures)


def test_a_sentence_without_an_abstention_keeps_its_clauses_together(packet):
    """Splitting every sentence would strand a short cited clause, dropping
    its citation from the claim it completes."""
    v = verify("apply calls claim; see [S1].", packet)
    assert "uncited claims" not in v.failures, v.failures


def _never_retries_packet():
    return build_packet(
        Context(
            project={"name": "demo"},
            task="t",
            symbols=[
                Symbol(
                    "pkg.apply",
                    "apply",
                    "Function",
                    "a.py",
                    1,
                    3,
                    source="def apply():\n    # never retries\n    claim()\n",
                ),
                Symbol("pkg.claim", "claim", "Function", "a.py", 4, 5, source="x"),
            ],
            graph_edges=[("pkg.apply", "pkg.claim", 1.0)],
        )
    )


@pytest.mark.parametrize(
    "text", ["apply calls claim and never retries", "calls claim, not a retry"]
)
def test_a_negation_of_a_separate_action_does_not_deny_the_link(text):
    check = check_item(
        "relations",
        text=text,
        packet=_never_retries_packet(),
        kind="calls",
        source="S1",
        target="S2",
    )
    assert "the relation's text denies its own link" not in check.failures


@pytest.mark.parametrize(
    "text",
    [
        "does not call",
        "never invokes",
        "is not called",
        "apply never, under any condition, calls claim",
    ],
)
def test_a_negated_link_verb_denies_the_link(text):
    check = check_item(
        "relations",
        text=text,
        packet=_never_retries_packet(),
        kind="calls",
        source="S1",
        target="S2",
    )
    assert "the relation's text denies its own link" in check.failures


def test_an_abstention_joined_by_a_bare_but_does_not_exempt_the_claim(packet):
    v = verify(
        "apply claims first [S1]. The packet does not show retries but apply "
        "deletes every row.",
        packet,
    )
    assert "uncited claims" in v.failures, v.failures


@pytest.mark.parametrize(
    "text",
    [
        "There is no evidence that apply and claim share a lock.",
        "The packet does not show whether apply retries while holding the row.",
    ],
)
def test_a_bare_and_or_while_inside_an_abstention_is_not_a_claim(packet, text):
    v = verify(text, packet)
    assert v.abstained is True, v
    assert "uncited claims" not in v.failures, v.failures
