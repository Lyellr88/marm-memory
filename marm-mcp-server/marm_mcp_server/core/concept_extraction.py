"""spaCy-based entity/relationship extraction for the concept graph.

Lazy/optional import mirroring settings.SEMANTIC_SEARCH_AVAILABLE's pattern —
base marm-mcp-server installs carry no spaCy dependency. Entity type taxonomy
layers concept/decision/pattern/error/tool categories (borrowed conceptually
from agentmemory's GraphNodeType, see research-notes.md §1-2) on top of
spaCy's raw NER output, rather than replacing it.
"""

import threading
from typing import NamedTuple, Optional

from ..config.settings import CONCEPTS_AVAILABLE

_MODEL_NAME = "en_core_web_sm"

# spaCy's raw NER labels we keep as-is (lowercased) rather than remapping —
# these are already meaningful entity types for MARM's content.
_KEPT_NER_LABELS = {"PERSON", "ORG", "GPE", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"}

# Keyword triggers for the taxonomy rule layer, checked against the sentence
# a noun chunk belongs to. Order matters — first match wins.
_TYPE_TRIGGERS = [
    ("error", ("error", "bug", "exception", "failure", "crash", "traceback")),
    ("decision", ("decided", "decision", "chose", "chose to", "opted", "agreed to")),
    ("pattern", ("pattern", "approach", "strategy", "convention", "architecture")),
    ("tool", ("library", "package", "framework", "tool", "dependency", "sdk")),
]

_MIN_CHUNK_TOKENS = 1
_STOPWORD_ONLY_SKIP = True
# Co-occurrence pairing is O(n^2) in entities-per-memory; a memory with many
# distinct entities (long/dense content) would otherwise generate hundreds of
# relationship rows from one extraction pass. Cap the pairing set, not
# extraction itself — all entities are still stored, only relationship-pair
# generation is bounded.
_MAX_ENTITIES_FOR_PAIRING = 25


class Entity(NamedTuple):
    name: str
    type: str


class ExtractionResult(NamedTuple):
    entities: list[Entity]
    relationship_pairs: list[
        tuple[str, str]
    ]  # (entity_name, entity_name) co-occurrence


_nlp = None
_nlp_lock = threading.Lock()
_nlp_failed = False


def _load_nlp_lazily():
    """Lazy singleton load, mirroring memory.py's _load_encoder_lazily pattern."""
    global _nlp, _nlp_failed
    if _nlp is not None:
        return _nlp
    if _nlp_failed or not CONCEPTS_AVAILABLE:
        return None
    with _nlp_lock:
        if _nlp is not None:
            return _nlp
        if _nlp_failed:
            return None
        try:
            import spacy

            _nlp = spacy.load(_MODEL_NAME)
        except Exception:
            _nlp_failed = True
            return None
    return _nlp


def _classify_chunk(chunk_text: str, sentence_text: str) -> Optional[str]:
    """Rule layer: classify a noun chunk as concept/decision/pattern/error/tool
    based on keyword triggers in its sentence, defaulting to 'concept'."""
    lowered_sentence = sentence_text.lower()
    for entity_type, keywords in _TYPE_TRIGGERS:
        if any(kw in lowered_sentence for kw in keywords):
            return entity_type
    return "concept"


def extract_entities(content: str) -> ExtractionResult:
    """Extract entities + co-occurrence relationship pairs from one memory's
    content string. Fail-open: returns an empty result if spaCy/the model
    isn't installed, never raises."""
    nlp = _load_nlp_lazily()
    if nlp is None:
        return ExtractionResult(entities=[], relationship_pairs=[])

    doc = nlp(content)
    seen_names: dict[str, str] = {}  # name -> type, first classification wins

    for ent in doc.ents:
        name = ent.text.strip()
        if not name or name in seen_names:
            continue
        label = ent.label_ if ent.label_ in _KEPT_NER_LABELS else None
        seen_names[name] = (
            label.lower()
            if label
            else _classify_chunk(name, ent.sent.text if ent.sent else content)
        )

    for chunk in doc.noun_chunks:
        name = chunk.text.strip()
        if not name or name in seen_names:
            continue
        if _STOPWORD_ONLY_SKIP and all(tok.is_stop or tok.is_punct for tok in chunk):
            continue
        if len(chunk) < _MIN_CHUNK_TOKENS:
            continue
        seen_names[name] = _classify_chunk(
            name, chunk.sent.text if chunk.sent else content
        )

    entities = [Entity(name=n, type=t) for n, t in seen_names.items()]

    names = list(seen_names.keys())[:_MAX_ENTITIES_FOR_PAIRING]
    relationship_pairs = [
        (names[i], names[j])
        for i in range(len(names))
        for j in range(i + 1, len(names))
    ]

    return ExtractionResult(entities=entities, relationship_pairs=relationship_pairs)
