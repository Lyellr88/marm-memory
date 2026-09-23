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
