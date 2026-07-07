"""Tests for core/concept_extraction.py.

The taxonomy rule layer (_classify_chunk) is pure and tested directly with
real inputs -- no mocks needed. Full NER-based extraction (extract_entities
with an actual loaded model) is skipped in this sandbox: en_core_web_sm's
model wheel is hosted on github.com releases, which this environment's
network policy blocks (same restriction that blocked huggingface.co during
the fastembed work). CONCEPTS_AVAILABLE is genuinely False here -- this also
lets the fail-open path be tested for real, not simulated.
"""

import pytest

from marm_mcp_server.core import concept_extraction
from marm_mcp_server.core.concept_extraction import (
    CONCEPTS_AVAILABLE,
    ExtractionResult,
    _classify_chunk,
    extract_entities,
)


def test_classify_chunk_detects_error_keyword():
    assert _classify_chunk("a timeout", "The request raised an exception after retry") == "error"


def test_classify_chunk_detects_decision_keyword():
    assert _classify_chunk("fastembed", "We decided to swap to fastembed for size") == "decision"


def test_classify_chunk_detects_pattern_keyword():
    assert _classify_chunk("the adapter", "This follows the same pattern as memory.py") == "pattern"


def test_classify_chunk_detects_tool_keyword():
    assert _classify_chunk("spacy", "spacy is a new library dependency") == "tool"


def test_classify_chunk_defaults_to_concept_with_no_trigger_keywords():
    assert _classify_chunk("the weather", "The weather was nice today") == "concept"


def test_concepts_unavailable_in_this_sandbox():
    """Documents why extraction-quality tests are skipped below -- if this
    ever flips True (e.g. CI has network access to github.com releases),
    the skipped test underneath should be un-skipped, not deleted."""
    assert CONCEPTS_AVAILABLE is False


def test_extract_entities_fails_open_when_model_unavailable():
    result = extract_entities("MARM stores memories with fastembed embeddings.")
    assert result == ExtractionResult(entities=[], relationship_pairs=[])


def test_load_nlp_lazily_returns_none_without_model():
    assert concept_extraction._load_nlp_lazily() is None


@pytest.mark.skipif(
    not CONCEPTS_AVAILABLE,
    reason="en_core_web_sm model not installed -- github.com releases blocked in this sandbox",
)
def test_extract_entities_real_ner_output():
    result = extract_entities(
        "Ryan decided to use spaCy for the rate limiter pattern in MARM."
    )
    names = {e.name for e in result.entities}
    assert "Ryan" in names
    assert len(result.entities) >= 2
