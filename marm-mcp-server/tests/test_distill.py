"""Tests for conversation distillation.

Every discrimination case here is a real sentence from this project's own
transcripts or memory store, not an invented one. The scorer was rebuilt once
already because it was calibrated against invented examples and then scored
the eight canonical MARM memories at +0.00 to +0.20, none of which cleared the
threshold. Synthetic positives hid that completely.
"""

from __future__ import annotations

import pytest

from marm_mcp_server.core.distill import (
    DEFAULT_THRESHOLD,
    DUPLICATE_AT,
    MAX_LENGTH,
    NEAR_AT,
    Candidate,
    Resolution,
    classify,
    extract_candidates,
    resolve,
)

# Real memories from the live store, and the shapes this must capture.
POSITIVES = [
    "marm-ctx weights call-graph edges by resolver strategy, not confidence alone.",
    "The code-graph daemon reparents to systemd and survives stopping the marm service.",
    "The concept graph reached 186 edges per memory at paragraph length.",
    "marm_delete removes log entries only, so bulk imports need the delete endpoint.",
    "An MCP server holds the module it imported when the agent session started.",
]

# Real conversational filler. None of these is a memory.
NEGATIVES = [
    "Okay, let me look at that and I will check the logs first.",
    "Run the tests again and then restart the service.",
    "Is that the right threshold for the duplicate check?",
    "It does that too, and that is why it happens.",
    "maybe we should probably look at the caching layer later",
    "Thanks, that works for me.",
    "I think you should try the other approach instead.",
    "Can you check whether the daemon is still running?",
]

spacy_model = pytest.importorskip("spacy", reason="concept model not bundled")


def _scores(sentences):
    """Score each sentence alone, with no threshold, as extract_candidates does."""
    out = {}
    for sentence in sentences:
        found = extract_candidates(sentence, threshold=-99.0, limit=50)
        out[sentence] = found[0].score if found else None
    return out


def test_real_memories_are_selected_and_chatter_is_not():
    """The property that matters: every positive outscores every negative.

    Asserted as separation rather than against a fixed threshold, so the
    threshold can be retuned without rewriting the test, and so a regression
    that merely shifts all scores does not read as a failure.
    """
    positive = _scores(POSITIVES)
    negative = _scores(NEGATIVES)

    missed = [s for s, v in positive.items() if v is None]
    assert not missed, f"real memories rejected outright: {missed}"

    kept_negatives = {s: v for s, v in negative.items() if v is not None}
    assert min(positive.values()) > max(kept_negatives.values()), (
        f"worst positive {min(positive.values()):+.2f} does not beat "
        f"best negative {max(kept_negatives.values()):+.2f}"
    )


def test_every_canonical_memory_clears_the_DEFAULT_threshold():
    """Separation is not enough: they must clear the floor actually shipped.

    The earlier test only asserted that positives outscore negatives, which
    stayed true while the default threshold sat above one of them. At 0.35,
    "The code-graph daemon reparents to systemd and survives stopping the marm
    service" scored +0.25 and was silently dropped -- found by rendering the
    Console page and noticing a sentence missing from the queue, not by the
    suite. This asserts the property that was actually broken.
    """
    missed = {
        sentence: score
        for sentence, score in _scores(POSITIVES).items()
        if score is None or score < DEFAULT_THRESHOLD
    }
    assert not missed, (
        f"real memories below the shipped default of {DEFAULT_THRESHOLD}: {missed}"
    )


def test_the_default_threshold_still_excludes_every_piece_of_chatter():
    """The other half. Lowering the floor must not start admitting filler."""
    admitted = {
        sentence: score
        for sentence, score in _scores(NEGATIVES).items()
        if score is not None and score >= DEFAULT_THRESHOLD
    }
    assert not admitted, f"chatter admitted at {DEFAULT_THRESHOLD}: {admitted}"


def test_imperative_is_rejected_but_a_hyphenated_identifier_is_not():
    """Regression: `marm-ctx ...` was thrown out as an imperative.

    spaCy splits `marm-ctx` into `marm` / `-` / `ctx` and tags the leading
    `marm` as VB, so the imperative guard fired on an identifier and discarded
    the single best example this feature exists to capture.
    """
    assert extract_candidates(
        "marm-ctx weights call-graph edges by resolver strategy, not confidence alone.",
        threshold=-99.0,
    ), "a hyphenated identifier was mistaken for an imperative verb"
    assert not extract_candidates(
        "Run the tests again and then restart the service.", threshold=-99.0
    ), "a real imperative was accepted"


def test_score_does_not_depend_on_the_preceding_sentence():
    """Regression: the tagger carried context across a sentence boundary.

    After a question, `marm_delete` was tagged PRON/PRP rather than PROPN, so
    the bare-pronoun penalty fired instead of the named-subject bonus and the
    same sentence scored +0.85 alone and +0.25 in context. A memory's quality
    cannot depend on what was said before it.
    """
    sentence = (
        "marm_delete removes log entries only, so bulk imports written through "
        "the internal endpoint need the delete endpoint instead."
    )
    alone = extract_candidates(sentence, threshold=-99.0)[0].score
    in_context = [
        c
        for c in extract_candidates(
            "Can you check whether the daemon is still running?\n" + sentence,
            threshold=-99.0,
        )
        if c.content.startswith("marm_delete")
    ]
    assert in_context, "the sentence vanished when a question preceded it"
    assert in_context[0].score == pytest.approx(alone, abs=0.01)


def test_a_mistagged_identifier_is_not_treated_as_a_pronoun():
    """Pins the lexical guard on its own, bypassing the standalone re-parse.

    Two independent fixes rescue the sentence above -- re-parsing it alone, and
    testing the pronoun class lexically -- so neither shows up when only one is
    removed. This asserts the lexical one directly, against the raw in-document
    span where `marm_delete` really is tagged PRON/PRP.
    """
    from marm_mcp_server.core.distill import _load_nlp_lazily, _shape_score

    nlp = _load_nlp_lazily()
    assert nlp is not None
    text = (
        "Can you check whether the daemon is still running?\n"
        "marm_delete removes log entries only, so bulk imports need the "
        "delete endpoint."
    )
    span = next(s for s in nlp(text).sents if s.text.startswith("marm_delete"))
    subject = next(t for t in span if t.dep_ in {"nsubj", "nsubjpass"})
    assert subject.pos_ == "PRON", (
        "premise gone: spaCy no longer mistags this identifier, so this test "
        "no longer covers the defect it was written for"
    )
    _, reasons = _shape_score(span)
    assert "names its subject" in reasons
    assert "subject is a bare pronoun" not in reasons


def test_a_real_pronoun_subject_is_still_penalised():
    """The lexical guard must not simply disable the penalty."""
    from marm_mcp_server.core.distill import _load_nlp_lazily, _shape_score

    nlp = _load_nlp_lazily()
    span = next(iter(nlp("That works for me.").sents))
    _, reasons = _shape_score(span)
    assert "subject is a bare pronoun" in reasons


def test_the_cap_bounds_the_queue_not_the_threshold():
    """Volume is controlled by `limit`.

    Measured on 49,833 words of real transcript the threshold barely bites --
    931 candidates at 0.35 and still 672 at 0.60 -- so the cap is what keeps a
    review queue reviewable.
    """
    text = " ".join(POSITIVES * 10)
    assert len(extract_candidates(text, limit=3)) <= 3
    assert len(extract_candidates(text, limit=1)) == 1


def test_identical_sentences_are_proposed_once_regardless_of_spelling():
    """Backticked and bare spellings of one sentence are one proposal."""
    text = (
        "MARM already has the parts (`marm_compaction` stages rather than "
        "auto-applies). "
        "MARM already has the parts (marm_compaction stages rather than "
        "auto-applies)."
    )
    assert len(extract_candidates(text, threshold=-99.0)) == 1


def test_a_heading_is_not_welded_to_the_paragraph_below_it():
    """A markdown heading has no full stop, so segmentation ran it into the
    following sentence and emitted a title welded to an unrelated clause."""
    text = (
        "## Two code fixes\n"
        "The distinctiveness gate refuses to link concepts whose names are "
        "shared across many repositories.\n"
    )
    contents = [c.content for c in extract_candidates(text, threshold=-99.0)]
    assert not any(
        c.startswith("Two code fixes") and "distinctiveness" in c for c in contents
    ), f"heading welded to the paragraph: {contents}"


def test_content_is_bounded_to_the_headline_band():
    long_sentence = "The server " + ("records every single event " * 40) + "always."
    for candidate in extract_candidates(long_sentence, threshold=-99.0):
        assert len(candidate.content) <= MAX_LENGTH


def test_empty_input_is_success_not_failure():
    assert extract_candidates("") == []
    assert extract_candidates("   \n  ") == []


@pytest.mark.parametrize(
    "cosine,expected",
    [
        (0.99, "duplicate"),
        (DUPLICATE_AT, "duplicate"),
        (0.90, "near"),
        (NEAR_AT, "near"),
        (0.81, "new"),
        (0.0, "new"),
    ],
)
def test_classify_bands(cosine, expected):
    assert classify(cosine) == expected


class _StubMemory:
    """Minimal stand-in exposing only what `resolve` actually touches."""

    def __init__(self, neighbours=None, encoder=True):
        self._neighbours = neighbours or []
        self._encoder = encoder
        self.encode_calls = 0

    def _load_encoder_lazily(self):
        return self._encoder

    def _encode_sync(self, text):
        import numpy as np

        self.encode_calls += 1
        # Deterministic direction per text, so two identical strings are
        # cosine 1.0 and two different ones are not.
        seed = abs(hash(text)) % (2**32)
        return np.random.default_rng(seed).normal(size=8)

    async def recall_similar(self, *args, **kwargs):
        return list(self._neighbours)


@pytest.mark.asyncio
async def test_resolve_without_an_encoder_reports_new_rather_than_failing():
    """A cold encoder must not sink the whole run.

    Nothing can be shown to be a duplicate, which is exactly what `new` means
    here; refusing to propose anything would be the worse answer.
    """
    stub = _StubMemory(encoder=False)
    out = await resolve(stub, [Candidate("something durable", 1.0, ())])
    assert out == [Resolution("new", 0.0, None, None)]
    assert stub.encode_calls == 0


@pytest.mark.asyncio
async def test_a_new_verdict_carries_no_neighbour():
    """Regression: below NEAR_AT there is no relationship to show.

    An invented sentence about descaling an espresso machine resolved `new` at
    0.758 against a chunk of the README, and the reviewer was invited to
    compare the two.
    """
    stub = _StubMemory(
        neighbours=[{"id": "m1", "content": "unrelated README text", "cosine": 0.758}]
    )
    (only,) = await resolve(stub, [Candidate("a wholly novel fact", 1.0, ())])
    assert only.verdict == "new"
    assert only.neighbour_id is None
    assert only.neighbour_content is None


@pytest.mark.asyncio
async def test_a_duplicate_carries_the_memory_it_duplicates():
    stub = _StubMemory(
        neighbours=[{"id": "m7", "content": "the stored version", "cosine": 0.97}]
    )
    (only,) = await resolve(stub, [Candidate("the restated version", 1.0, ())])
    assert only.verdict == "duplicate"
    assert only.neighbour_id == "m7"
    assert only.neighbour_content == "the stored version"


@pytest.mark.asyncio
async def test_a_candidate_duplicating_an_earlier_candidate_is_caught_in_batch():
    """A transcript restates its own conclusions.

    Resolved against the batch before the store, so the second copy is never
    reported as novel and never reaches the database.
    """
    stub = _StubMemory(neighbours=[])
    same = "the code graph daemon reparents to systemd"
    out = await resolve(stub, [Candidate(same, 1.0, ()), Candidate(same, 1.0, ())])
    assert out[0].verdict == "new"
    assert out[1].verdict == "duplicate"
    assert out[1].neighbour_id is None
    assert out[1].neighbour_content == same


# --- staging loop -----------------------------------------------------------
#
# Driven against a real SQLite file rather than a stubbed connection, because
# the properties being asserted here (the unique hash index, the claim before
# the write) are enforced by the schema and a stub would assert nothing.


@pytest.fixture()
def staged(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    server = load_isolated_server(monkeypatch, tmp_path)
    from marm_mcp_server.core.memory import memory as live
    from marm_mcp_server.services import distill as service

    assert server is not None
    return service, live


def _propose(service, live, text, **kwargs):
    import asyncio

    return asyncio.run(
        service.propose(live, text, session_name="t", threshold=-99.0, **kwargs)
    )


def test_propose_stages_and_a_rerun_stages_nothing(staged):
    service, live = staged
    text = POSITIVES[1]

    first = _propose(service, live, text)
    assert first["staged"] >= 1
    assert all(p.get("id") for p in first["proposals"] if p["staged"])

    again = _propose(service, live, text)
    assert again["staged"] == 0, "a re-run must not enqueue the same proposal twice"
    assert all(
        p.get("note") == "already proposed, or already reviewed"
        for p in again["proposals"]
        if not p["staged"]
    )


def test_review_lists_only_pending_and_discard_removes_it(staged):
    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]

    assert service.review(live, session_name="t")["count"] == 1

    assert service.discard(live, proposal_id)["status"] == "success"
    assert service.review(live, session_name="t")["count"] == 0

    # Discarding twice is an error, not a silent success.
    assert service.discard(live, proposal_id)["status"] == "error"


def test_a_discarded_proposal_is_never_offered_again(staged):
    """Deliberate: re-offering a rejected proposal is how a queue stops being
    read. The unique hash index is what enforces it."""
    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]
    service.discard(live, proposal_id)

    assert _propose(service, live, POSITIVES[1])["staged"] == 0
    assert service.review(live, session_name="t")["count"] == 0


def test_apply_writes_once_and_refuses_a_second_time(staged):
    import asyncio

    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]

    first = asyncio.run(service.apply(live, proposal_id))
    assert first["status"] == "success"
    assert first["memory_id"]

    second = asyncio.run(service.apply(live, proposal_id))
    assert second["status"] == "error"
    assert "already applied" in second["error"]


def test_a_failed_write_leaves_the_proposal_retryable(staged, monkeypatch):
    """The row is claimed before the write, so a failure must release it.

    The wrong way round would leave a proposal marked applied with no memory
    behind it -- unrecoverable, and invisible.
    """
    import asyncio

    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]

    async def boom(*args, **kwargs):
        raise RuntimeError("write queue is down")

    monkeypatch.setattr(live, "store_memory_queued", boom)
    failed = asyncio.run(service.apply(live, proposal_id))
    assert failed["status"] == "error"
    assert "write failed" in failed["error"]

    monkeypatch.undo()
    assert service.review(live, session_name="t")["count"] == 1
    assert asyncio.run(service.apply(live, proposal_id))["status"] == "success"


def test_nothing_durable_is_a_success_not_an_error(staged):
    service, live = staged
    result = _propose(service, live, "Okay. Thanks, that works for me.")
    assert result["status"] == "success"
    assert result["proposals"] == []
    assert "not an error" in result["note"]
