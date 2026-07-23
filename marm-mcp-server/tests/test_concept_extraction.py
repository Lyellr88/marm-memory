"""Tests for core/concept_extraction.py.

The taxonomy rule layer (_classify_chunk) is pure and tested directly with
real inputs -- no mocks needed. Full NER-based extraction is skipped only when
the installed environment is missing spaCy; the English pipeline data itself is
bundled in the MARM distribution.
"""

import pytest

from marm_mcp_server.core import concept_extraction
from marm_mcp_server.core.concept_extraction import (
    CONCEPT_MODEL_PATH,
    CONCEPTS_AVAILABLE,
    ExtractionResult,
    _classify_chunk,
    _classify_predicate,
    _lowest_common_ancestor,
    _nearest_verb_ancestor,
    _same_sentence,
    extract_entities,
)


def test_bundled_concept_model_data_is_present():
    assert (CONCEPT_MODEL_PATH / "config.cfg").is_file()
    assert (CONCEPT_MODEL_PATH / "ner" / "model").is_file()


class _FakeToken:
    """Stands in for a spaCy Token -- only the attributes _classify_predicate's
    dependency-parse walk actually reads (.i, .head, .pos_, .lemma_)."""

    def __init__(self, i, pos_="NOUN", lemma_="", head=None):
        self.i = i
        self.pos_ = pos_
        self.lemma_ = lemma_
        self.head = head if head is not None else self  # self-loop = sentence root


class _FakeSpan:
    """Stands in for a spaCy Span -- only .root and .sent."""

    def __init__(self, root, sent=None):
        self.root = root
        self.sent = sent


class _FakeSent:
    """Stands in for a spaCy sentence Span -- only .start is read."""

    def __init__(self, start):
        self.start = start


def test_classify_chunk_detects_error_keyword():
    assert (
        _classify_chunk("a timeout", "The request raised an exception after retry")
        == "error"
    )


def test_classify_chunk_detects_decision_keyword():
    assert (
        _classify_chunk("fastembed", "We decided to swap to fastembed for size")
        == "decision"
    )


def test_classify_chunk_detects_pattern_keyword():
    assert (
        _classify_chunk("the adapter", "This follows the same pattern as memory.py")
        == "pattern"
    )


def test_classify_chunk_detects_tool_keyword():
    assert _classify_chunk("spacy", "spacy is a new library dependency") == "tool"


def test_classify_chunk_defaults_to_concept_with_no_trigger_keywords():
    assert _classify_chunk("the weather", "The weather was nice today") == "concept"


@pytest.fixture
def unavailable_concept_model(monkeypatch):
    monkeypatch.setattr(
        concept_extraction,
        "CONCEPT_MODEL_PATH",
        CONCEPT_MODEL_PATH.parent / "__missing_concept_model__",
    )
    monkeypatch.setattr(concept_extraction, "CONCEPTS_AVAILABLE", True)
    monkeypatch.setattr(concept_extraction, "_nlp", None)
    monkeypatch.setattr(concept_extraction, "_nlp_failed", False)
    yield
    concept_extraction._nlp = None
    concept_extraction._nlp_failed = False


def test_extract_entities_fails_open_when_model_unavailable(unavailable_concept_model):
    result = extract_entities("MARM stores memories with fastembed embeddings.")
    assert result == ExtractionResult(entities=[], relationship_pairs=[])


def test_load_nlp_lazily_returns_none_without_model(unavailable_concept_model):
    assert concept_extraction._load_nlp_lazily() is None


@pytest.mark.skipif(
    not CONCEPTS_AVAILABLE,
    reason="spaCy is not installed in this test environment",
)
def test_extract_entities_real_ner_output():
    result = extract_entities(
        "Ryan decided to use spaCy for the rate limiter pattern in MARM."
    )
    names = {e.name for e in result.entities}
    assert "Ryan" in names
    assert len(result.entities) >= 2


@pytest.mark.skipif(
    not CONCEPTS_AVAILABLE,
    reason="spaCy is not installed in this test environment",
)
def test_extract_entities_real_typed_predicate():
    """Same-sentence entities with a real verb link get a typed predicate,
    not the generic co_occurs_with fallback."""
    result = extract_entities("The team fixed the auth bug yesterday.")
    predicates = {(p.source, p.target): p.predicate for p in result.relationship_pairs}
    assert any(pred == "fixes" for pred in predicates.values())


# ── _classify_predicate and its helpers (pure, fake spaCy stand-ins) ────


def test_lowest_common_ancestor_finds_shared_verb_root():
    # "The team fixed the auth bug": team <- fixed -> bug (fixed is root)
    fixed = _FakeToken(2, pos_="VERB", lemma_="fix")
    team = _FakeToken(1, pos_="NOUN", head=fixed)
    bug = _FakeToken(5, pos_="NOUN", head=fixed)
    assert _lowest_common_ancestor(team, bug) is fixed


def test_lowest_common_ancestor_walks_multi_level_chains():
    # root <- mid <- leaf_a, root <- leaf_b
    root = _FakeToken(0, pos_="VERB", lemma_="run")
    mid = _FakeToken(1, pos_="NOUN", head=root)
    leaf_a = _FakeToken(2, pos_="NOUN", head=mid)
    leaf_b = _FakeToken(3, pos_="NOUN", head=root)
    assert _lowest_common_ancestor(leaf_a, leaf_b) is root


def test_nearest_verb_ancestor_returns_self_when_already_verb():
    fixed = _FakeToken(2, pos_="VERB", lemma_="fix")
    assert _nearest_verb_ancestor(fixed) is fixed


def test_nearest_verb_ancestor_walks_up_to_find_verb():
    fixed = _FakeToken(2, pos_="VERB", lemma_="fix")
    noun = _FakeToken(3, pos_="NOUN", head=fixed)
    assert _nearest_verb_ancestor(noun) is fixed


def test_nearest_verb_ancestor_returns_none_when_no_verb_in_chain():
    # A bare noun-phrase list root with no verb anywhere in its own chain.
    redis = _FakeToken(0, pos_="PROPN", lemma_="Redis")  # self-loop root
    assert _nearest_verb_ancestor(redis) is None


def test_classify_predicate_detects_fixes_via_dependency_parse():
    fixed = _FakeToken(2, pos_="VERB", lemma_="fix")
    team = _FakeToken(1, pos_="NOUN", head=fixed)
    bug = _FakeToken(5, pos_="NOUN", head=fixed)
    span_a = _FakeSpan(root=team)
    span_b = _FakeSpan(root=bug)
    assert _classify_predicate(span_a, span_b) == "fixes"


def test_classify_predicate_returns_related_to_when_no_verb_link():
    # "Redis, Postgres, and Kafka" -- Kafka.head = Redis (conj), no verb.
    redis = _FakeToken(0, pos_="PROPN", lemma_="Redis")
    kafka = _FakeToken(4, pos_="PROPN", lemma_="Kafka", head=redis)
    span_a = _FakeSpan(root=redis)
    span_b = _FakeSpan(root=kafka)
    assert _classify_predicate(span_a, span_b) == "related_to"


def test_classify_predicate_returns_related_to_when_verb_not_in_trigger_list():
    ran = _FakeToken(1, pos_="VERB", lemma_="run")
    a = _FakeToken(0, pos_="NOUN", head=ran)
    b = _FakeToken(2, pos_="NOUN", head=ran)
    span_a = _FakeSpan(root=a)
    span_b = _FakeSpan(root=b)
    assert _classify_predicate(span_a, span_b) == "related_to"


# ── _same_sentence ───────────────────────────────────────────────────


def test_same_sentence_true_for_matching_sent_starts():
    span_a = _FakeSpan(root=_FakeToken(0), sent=_FakeSent(start=0))
    span_b = _FakeSpan(root=_FakeToken(1), sent=_FakeSent(start=0))
    assert _same_sentence(span_a, span_b) is True


def test_same_sentence_false_for_different_sent_starts():
    span_a = _FakeSpan(root=_FakeToken(0), sent=_FakeSent(start=0))
    span_b = _FakeSpan(root=_FakeToken(10), sent=_FakeSent(start=8))
    assert _same_sentence(span_a, span_b) is False


def test_same_sentence_false_when_sent_is_none():
    span_a = _FakeSpan(root=_FakeToken(0), sent=None)
    span_b = _FakeSpan(root=_FakeToken(1), sent=_FakeSent(start=0))
    assert _same_sentence(span_a, span_b) is False
