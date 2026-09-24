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
    v = verify(f"Bindings are created by `{span}` [S1].", bind_packet)
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
    def packet(label, truncated):
        return build_packet(
            Context(
                project={"name": "demo"},
                task="how",
                symbols=[
                    Symbol(
                        "pkg.a",
                        "a",
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
