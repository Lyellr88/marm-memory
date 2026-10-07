"""Propose durable memories from raw conversation, and resolve them against
what is already stored.

WHY THIS IS SELECTION AND NOT GENERATION
    Other memory layers do this with an LLM: feed it the transcript, let it
    write facts, let it decide ADD / UPDATE / DELETE against existing rows.
    MARM has no generative model. It has spaCy and a sentence encoder, both
    local, and adding an LLM would mean either a cloud call -- which this
    deployment exists to avoid -- or a second inference stack.

    So this SELECTS sentences that already read like durable facts and
    normalises them, rather than writing new ones. That is a real limitation
    and it is also a decent fit: MARM memories are headlines, and a headline
    is usually a sentence someone already said. "marm-ctx weights call-graph
    edges by resolver strategy, not confidence alone" was typed, not
    synthesised.

    The consequence to be honest about: a fact spread across three turns, or
    implied but never stated, will not be proposed. This finds what was said
    plainly, not what was meant.

WHY IT PROPOSES RATHER THAN WRITES
    The same reason `marm_compaction` stages instead of applying: a similarity
    threshold on entity names produces enough false positives that anything
    writing memory unattended on such a score poisons the store faster than it
    fills it -- two adjacent version strings score as near-identical.

    Resolution is deliberately three-valued, not four. An LLM-backed pipeline
    can classify a near-match as "supersedes" or "contradicts"; an encoder
    cannot tell those apart, because both look like "close but not identical".
    Guessing would be worse than declining, so a near match is surfaced WITH
    its neighbour and left for a reviewer.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any, Mapping, NamedTuple, Optional, Sequence

import numpy as np

from .concept_extraction import _load_nlp_lazily
from .distill_selection import (
    _DANGLING_START,
    _dedupe_key,
    _demarkdown,
    _normalise,
    _reparse,
    _shape_score,
    _usable,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .memory import MARMMemory

# The headline band. The live store averages 191 characters, and the reason is
# measured rather than aesthetic: re-imported at paragraph length the concept
# graph reached 186 edges per memory and minutes of build time; at headline
# length it is 27.4 edges and 49 seconds. Long detail belongs in metadata.
MIN_LENGTH = 40
MAX_LENGTH = 240

# Cosine bands, shared with write-time consolidation so the two agree about
# what "the same memory" means.
DUPLICATE_AT = 0.92
NEAR_AT = 0.82

# Selection defaults. See `extract_candidates` for why the cap, not the
# threshold, is what keeps the queue reviewable.
# Calibrated against real memories rather than invented examples: a higher
# threshold discarded genuine memories without excluding any more chatter,
# because a terse technical assertion can score close to one. The threshold is
# FOR excluding chatter; volume is `DEFAULT_LIMIT`'s job, and it alone.
DEFAULT_THRESHOLD = 0.20
DEFAULT_LIMIT = 20

#: How much transcript the generation path sends. Well inside a 64k-token
#: window at roughly 4 characters per token, leaving room for the reply.
_LLM_INPUT_CHARS = int(os.environ.get("MARM_DISTILL_INPUT_CHARS") or 48000)

# How deep to look for a nearest neighbour. Consolidation uses the same shape:
# rank a handful and take the best, rather than trusting the top hit, because
# the fused "similarity" score is not the cosine and can reorder them.
_NEIGHBOURS = 5


class Candidate(NamedTuple):
    """One proposed memory, before it meets the store.

    `evidence` is the verbatim span the fact came from. It is empty for the
    selection path, where the content IS the original span, and populated by
    the generation path, where it is the mitigation for the context collapse
    that extraction otherwise causes (arXiv 2601.00821).
    """

    content: str
    score: float
    reasons: tuple[str, ...]
    evidence: str = ""
    context_type: str = ""


class Resolution(NamedTuple):
    """What the store has to say about a candidate.

    `verdict` is one of:
      new        nothing close enough to be the same memory
      duplicate  already stored; writing it again adds nothing
      near       close to something stored, and an encoder cannot say whether
                 it refines it, contradicts it, or is simply adjacent
    """

    verdict: str
    cosine: float
    neighbour_id: Optional[str]
    neighbour_content: Optional[str]


def extract_candidates(
    text: str, *, threshold: float = DEFAULT_THRESHOLD, limit: int = DEFAULT_LIMIT
) -> list[Candidate]:
    """Select sentences from `text` that read like durable facts.

    Returns highest-scoring first, capped at `limit`. An empty list is a
    legitimate answer and means the transcript said nothing worth keeping in
    this shape.

    THE CAP IS THE REAL CONTROL, NOT THE THRESHOLD, and that was measured
    rather than assumed. Over 49,833 words of real transcript the threshold
    barely bites: 931 candidates at 0.35 and still 672 at 0.60, because dense
    technical prose satisfies "named subject, indicative verb, specific object"
    almost everywhere. Raising the threshold to cut volume therefore discards
    good memories long before it discards enough of them to matter -- which is
    not hypothetical: the default WAS 0.35, and at that floor 14% of the live
    store and one of the five canonical MARM-Stack memories fell below it.

    So the threshold's job is to exclude chatter -- where it is decisive, since
    conversational filler scores negative -- and the cap's job is to keep a
    review queue a person will actually work through. A reviewer handed 672
    proposals reviews none of them.
    """
    nlp = _load_nlp_lazily()
    if nlp is None or not text.strip():
        return []

    seen: set[str] = set()
    out: list[Candidate] = []
    stripped = _demarkdown(text)

    for span in nlp(stripped).sents:
        if not _usable(span):
            continue
        content = _normalise(span.text)
        if not (MIN_LENGTH <= len(content) <= MAX_LENGTH):
            continue
        key = _dedupe_key(content)
        if key in seen:
            continue
        seen.add(key)
        score, reasons = _shape_score(_reparse(nlp, content, span))
        if score >= threshold:
            out.append(
                Candidate(
                    content=content, score=round(score, 3), reasons=tuple(reasons)
                )
            )

    return sorted(out, key=lambda c: -c.score)[:limit]


def classify(cosine: float) -> str:
    """Map a nearest-neighbour cosine onto a verdict.

    The bands match write-time consolidation so `marm_distill` and a direct
    `marm_log_entry` cannot disagree about what counts as a duplicate.
    """
    if cosine >= DUPLICATE_AT:
        return "duplicate"
    if cosine >= NEAR_AT:
        return "near"
    return "new"


async def resolve(
    memory: "MARMMemory",
    candidates: Sequence[Candidate],
    *,
    session: str | None = None,
    project: str | None = None,
) -> list[Resolution]:
    """Ask the store what it already knows about each candidate.

    Resolution is against the WHOLE store by default, not one session, and that
    is the difference from write-time consolidation. `find_semantic_duplicate`
    scopes to `session_name` because it guards a single write; a distil run is
    asking "has this ever been recorded", and a fact learned in one session and
    re-stated in another is the exact duplicate this exists to catch.

    Candidates are also resolved against EACH OTHER. A transcript restates its
    own conclusions -- measured on real input, one run proposed the same numpy
    finding twice in different words -- and proposing both wastes the reviewer's
    attention on a decision the tool can make itself.

    An unavailable encoder yields all-`new` rather than an error. That is the
    honest answer: nothing can be shown to be a duplicate, and refusing to
    propose anything because the encoder is cold would be worse than proposing
    with an unknown neighbour.
    """
    out: list[Resolution] = []
    accepted: list[tuple[str, np.ndarray]] = []

    encoder = None
    try:
        encoder = memory._load_encoder_lazily()
    except Exception:  # pragma: no cover - defensive, encoder is optional
        logger.exception("distill: encoder probe failed")

    for candidate in candidates:
        if not encoder:
            out.append(Resolution("new", 0.0, None, None))
            continue

        vector = None
        try:
            # `_encode_sync` and not `encoder.encode`: the encoder is shared and
            # the lock inside it is there to stop concurrent use hanging. It is
            # blocking, so it goes off the event loop.
            vector = np.asarray(
                await asyncio.to_thread(memory._encode_sync, candidate.content)
            )
        except Exception:
            logger.exception("distill: could not encode a candidate")

        # Against the batch first: it is free, it needs no database round trip,
        # and a candidate that duplicates an earlier candidate should never be
        # reported against the store as if it were novel.
        if vector is not None:
            twin = _nearest_in_batch(vector, accepted)
            if twin is not None and twin[1] >= DUPLICATE_AT:
                out.append(Resolution("duplicate", round(twin[1], 4), None, twin[0]))
                continue

        try:
            rows = await memory.recall_similar(
                candidate.content,
                session=session,
                limit=_NEIGHBOURS,
                query_vec=vector,
                project=project,
                exact_mode="semantic",
                with_cosine=True,
            )
        except Exception:
            logger.exception("distill: recall failed for a candidate")
            rows = []

        # The generation path quotes a verbatim span, and when that span is
        # itself the text of a stored memory the store already says this --
        # which no cosine can be trusted to notice. A fact extracted out of a
        # long paragraph memory resolves `new`, because the paragraph's
        # embedding is dominated by everything else it says while the generated
        # content is a paraphrase that misses on the surface too.
        #
        # Containment rather than a lower NEAR_AT: a normalised substring
        # match means the store literally contains the sentence, so it has no
        # false positives, where widening the band trades these for real ones.
        twin_row = _containing_row(candidate.evidence, rows)
        scored = [r for r in rows if "cosine" in r]
        if twin_row is not None:
            out.append(
                Resolution(
                    verdict="duplicate",
                    cosine=round(float(twin_row.get("cosine") or 0.0), 4),
                    neighbour_id=str(twin_row["id"]),
                    neighbour_content=str(twin_row.get("content") or ""),
                )
            )
        elif not scored:
            out.append(Resolution("new", 0.0, None, None))
        else:
            nearest = max(scored, key=lambda r: r["cosine"])
            cosine = float(nearest["cosine"])
            verdict = classify(cosine)
            # A `new` verdict has no neighbour worth showing, and attaching the
            # nearest row anyway is actively misleading: measured, an invented
            # sentence about descaling an espresso machine resolved `new` at
            # 0.758 against a chunk of the README, which a reviewer would be
            # invited to compare it with. Below NEAR_AT there is no relationship.
            out.append(
                Resolution(
                    verdict=verdict,
                    cosine=round(cosine, 4),
                    neighbour_id=str(nearest["id"]) if verdict != "new" else None,
                    neighbour_content=(
                        str(nearest.get("content") or "") if verdict != "new" else None
                    ),
                )
            )

        if vector is not None:
            accepted.append((candidate.content, vector))

    return out


def _nearest_in_batch(
    vector: "np.ndarray", accepted: Sequence[tuple[str, "np.ndarray"]]
) -> Optional[tuple[str, float]]:
    """Closest already-accepted candidate in this batch, as (content, cosine)."""
    best: Optional[tuple[str, float]] = None
    for content, other in accepted:
        denominator = float(np.linalg.norm(vector) * np.linalg.norm(other))
        if denominator <= 0:
            continue
        cosine = float(np.dot(vector, other) / denominator)
        if best is None or cosine > best[1]:
            best = (content, cosine)
    return best


# ---------------------------------------------------------------------------
# Generation-backed extraction.
#
# Everything above selects sentences that already read like memories. That is
# what MARM can do with no generative model, and it stays the fallback. When a
# local model IS reachable this does the job properly: it writes SELF-CONTAINED
# facts, which selection cannot, because a sentence lifted out of a transcript
# keeps whatever its neighbours were carrying for it.
#
# Two findings from the 2026 literature shaped this, and they pull in opposite
# directions:
#
#   - Extraction beats summarisation, and a memory should be self-contained --
#     carrying its own subject and specifics rather than depending on the turn
#     it came from (mem0's 2026 guidance).
#   - But extracted artifacts LOSE against verbatim chunks on multi-hop and
#     nuance, through "context collapse": the relations between facts vanish
#     with the surrounding text (arXiv 2601.00821).
#
# The resolution here is to refuse to choose. Each proposal carries the rewritten
# self-contained fact AND the verbatim span it came from, so retrieval gets the
# headline and a reader gets the original. MARM already has the place to put it:
# the memory is the headline, the evidence goes in `metadata`.

_LLM_SYSTEM = """\
You extract durable facts from a technical conversation so they can be stored \
as long-term memory for an engineering project.

Return ONLY a JSON array. Each element:
  {"content": str, "evidence": str, "context_type": str}

RULES
1. `content` must be SELF-CONTAINED. A reader six months from now sees only \
this sentence, with no transcript. Name the subject explicitly. Never open with \
"it", "this", "that", "they" or "there".
2. `content` must be one assertion, stated plainly, under 240 characters.
3. `evidence` MUST be copied VERBATIM from the conversation -- an exact \
substring, character for character. It is checked. If you cannot copy an exact \
span that supports the fact, omit the fact entirely.
4. Extract only what the conversation actually STATES. Do not infer, do not \
generalise, do not add knowledge of your own. A plausible fact that was not \
said is worse than a missing one.
5. Skip questions, greetings, instructions, plans, and anything only true \
during this conversation.
6. `context_type` is one of: decision, finding, constraint, error, tool, \
general.

Prefer few, high-quality facts. An empty array is a correct answer.\
"""


def _llm_usable(fact: object, haystack: str) -> Optional[Candidate]:
    """Validate one model-proposed fact, or reject it.

    The evidence check is the point. A model asked for a verbatim span and
    given a transcript can still invent one, and an invented span is the exact
    signature of an invented fact -- so a proposal whose evidence is not
    actually in the input is dropped rather than shown to a reviewer. This is
    cheap, deterministic, and catches the failure that matters most in a
    memory store: a confident sentence nobody ever said.
    """
    if not isinstance(fact, dict):
        return None
    content = _normalise(str(fact.get("content") or ""))
    evidence = str(fact.get("evidence") or "").strip()
    if not content or not evidence:
        return None
    if not (MIN_LENGTH <= len(content) <= MAX_LENGTH):
        return None
    if _DANGLING_START.match(content):
        return None

    # Compare on collapsed whitespace: models normalise line breaks and indent
    # when copying, and that is not the failure this guard is looking for. A
    # span shorter than a memory can be occurs in almost any transcript, so it
    # verifies nothing.
    needle = _squash(evidence)
    if len(needle) < MIN_LENGTH or needle not in _squash(haystack):
        return None

    context_type = str(fact.get("context_type") or "general").strip().lower()
    if context_type not in _CONTEXT_TYPES:
        context_type = "general"

    return Candidate(
        content=content,
        score=1.0,
        reasons=("extracted by the local model", f"type: {context_type}"),
        evidence=evidence[:1000],
        context_type=context_type,
    )


_CONTEXT_TYPES = frozenset(
    {"decision", "finding", "constraint", "error", "tool", "general"}
)


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _containing_row(
    evidence: str, rows: Sequence[Mapping[str, Any]]
) -> Optional[Mapping[str, Any]]:
    """The recalled memory that already contains this evidence span, if any.

    Only the rows recall returned are checked, so a memory that quotes the
    span but ranks outside `_NEIGHBOURS` is still missed -- the cheap half of
    the fix, and the half that covers what was actually observed.

    `MIN_LENGTH` is the floor rather than a new constant: it is already the
    length below which a span is too slight to be a memory, and it is exactly
    the property that stops a short fragment matching half the store.
    """
    needle = _squash(evidence)
    if len(needle) < MIN_LENGTH:
        return None
    for row in rows:
        if row.get("id") and needle in _squash(str(row.get("content") or "")):
            return row
    return None


def llm_extract(text: str, *, limit: int = DEFAULT_LIMIT) -> Optional[list[Candidate]]:
    """Extract self-contained facts with the local model.

    Returns None when no model is reachable, which is the caller's signal to
    fall back to `extract_candidates`. An empty list is a real answer meaning
    the conversation held nothing durable.
    """
    from ..services import local_llm

    if not text.strip() or local_llm.available() is None:
        return None

    # The window is finite and a transcript is not. Take the tail: a
    # conversation's conclusions are at the end, and the beginning is usually
    # the part that was still being worked out.
    excerpt = text[-_LLM_INPUT_CHARS:] if len(text) > _LLM_INPUT_CHARS else text

    facts = local_llm.complete_json(
        _LLM_SYSTEM,
        f"Conversation:\n\n{excerpt}\n\nReturn the JSON array now.",
        max_tokens=2048,
    )
    if facts is None:
        return None
    if isinstance(facts, dict):
        # Some servers honour response_format by wrapping the array in an
        # object; accept the common shapes rather than failing the run.
        for key in ("facts", "memories", "items", "results", "data"):
            if isinstance(facts.get(key), list):
                facts = facts[key]
                break
    if not isinstance(facts, list):
        return None

    out: list[Candidate] = []
    seen: set[str] = set()
    for fact in facts:
        candidate = _llm_usable(fact, text)
        if candidate is None:
            continue
        key = _dedupe_key(candidate.content)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out[:limit]
