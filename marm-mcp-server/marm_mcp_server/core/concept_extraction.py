"""spaCy-based entity/relationship extraction for the concept graph."""

import threading
from typing import TYPE_CHECKING, NamedTuple, Optional

from ..config.settings import CONCEPT_MODEL_PATH, CONCEPTS_AVAILABLE

if TYPE_CHECKING:
    from spacy.tokens import Span, Token

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

# Keyword triggers for the pairwise predicate classifier -- matched against
# the lemma of the lowest-common-ancestor verb between two entity spans in
# the same sentence. Same ordered, first-match-wins shape as _TYPE_TRIGGERS.
_PREDICATE_TRIGGERS = [
    ("fixes", ("fix", "resolve", "patch")),
    ("implements", ("implement", "build", "create", "add")),
    ("depends_on", ("depend", "require", "need")),
    ("uses", ("use", "leverage", "call", "invoke")),
    ("causes", ("cause", "trigger", "lead")),
    ("replaces", ("replace", "supersede", "deprecate")),
    ("extends", ("extend", "inherit", "subclass")),
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


class RelationshipPair(NamedTuple):
    source: str
    target: str
    predicate: str


class ExtractionResult(NamedTuple):
    entities: list[Entity]
    relationship_pairs: list[RelationshipPair]


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

            _nlp = spacy.load(CONCEPT_MODEL_PATH)
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


def _ancestor_chain(token: "Token") -> list:
    """token, its head, its head's head, ... up to the sentence root (where
    token.head == token, spaCy's self-loop convention). Always terminates —
    every parsed token has exactly one path to its sentence root."""
    chain = [token]
    current = token
    while current.head.i != current.i:
        current = current.head
        chain.append(current)
    return chain


def _lowest_common_ancestor(token_a: "Token", token_b: "Token"):
    """First token in token_a's ancestor chain that also appears in
    token_b's — the syntactic point where the two entities' dependency
    paths converge. None only if token_a/token_b aren't in the same
    sentence (their chains would never intersect); callers only invoke
    this for confirmed same-sentence pairs."""
    chain_a = _ancestor_chain(token_a)
    ancestors_b = {tok.i for tok in _ancestor_chain(token_b)}
    for tok in chain_a:
        if tok.i in ancestors_b:
            return tok
    return None


def _nearest_verb_ancestor(token: "Token"):
    """token itself if already VERB/AUX, else the nearest VERB/AUX walking
    up its own head chain, else None if the sentence root has no verb
    (e.g. a bare noun-phrase list with no verb at all)."""
    for tok in _ancestor_chain(token):
        if tok.pos_ in ("VERB", "AUX"):
            return tok
    return None


def _same_sentence(span_a: "Span", span_b: "Span") -> bool:
    sent_a = span_a.sent
    sent_b = span_b.sent
    if sent_a is None or sent_b is None:
        return False
    return sent_a.start == sent_b.start


def _classify_predicate(span_a: "Span", span_b: "Span") -> str:
    """Lowest-common-ancestor verb between two entity spans, matched against
    _PREDICATE_TRIGGERS by lemma. Mirrors _classify_chunk's ordered-trigger,
    first-match-wins style. Only meaningful for same-sentence pairs (see
    extract_entities's pairing loop) -- defaults to 'related_to' when no
    verb link exists, e.g. a bare list ("Redis, Postgres, and Kafka") with
    no shared verb."""
    lca = _lowest_common_ancestor(span_a.root, span_b.root)
    if lca is None:
        return "related_to"

    verb = _nearest_verb_ancestor(lca)
    if verb is None:
        return "related_to"

    lemma = verb.lemma_.lower()
    for predicate, keywords in _PREDICATE_TRIGGERS:
        if any(kw in lemma for kw in keywords):
            return predicate
    return "related_to"


def extract_entities(content: str) -> ExtractionResult:
    """Extract entities + relationship pairs from one memory's content
    string. Fail-open: returns an empty result if spaCy/the model isn't
    installed, never raises.

    Relationship predicates: same-sentence pairs are classified via
    _classify_predicate (dependency-parse based, see above); cross-sentence
    pairs (first mentions land in different sentences -- no shared
    syntactic context to classify from) keep the generic "co_occurs_with".
    These are deliberately different fallback tiers, not collapsed into one
    default -- they represent different confidence levels.
    """
    nlp = _load_nlp_lazily()
    if nlp is None:
        return ExtractionResult(entities=[], relationship_pairs=[])

    doc = nlp(content)
    seen_names: dict[str, str] = {}  # name -> type, first classification wins
    seen_spans: dict[str, "Span"] = {}  # name -> span, first occurrence wins

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
        seen_spans[name] = ent

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
        seen_spans[name] = chunk

    entities = [Entity(name=n, type=t) for n, t in seen_names.items()]

    names = list(seen_names.keys())[:_MAX_ENTITIES_FOR_PAIRING]
    relationship_pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            span_a = seen_spans[names[i]]
            span_b = seen_spans[names[j]]
            if _same_sentence(span_a, span_b):
                predicate = _classify_predicate(span_a, span_b)
            else:
                predicate = "co_occurs_with"
            relationship_pairs.append(RelationshipPair(names[i], names[j], predicate))

    return ExtractionResult(entities=entities, relationship_pairs=relationship_pairs)
