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


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


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


# --- generation-backed extraction ------------------------------------------
#
# The evidence check is the load-bearing guard here. A model asked for a
# verbatim span can invent one, and an invented span is the signature of an
# invented fact -- the single worst failure for a memory store, because the
# result is a confident sentence nobody ever said.

TRANSCRIPT = (
    "We decided to cap distill proposals at twenty because raising the shape "
    "threshold barely changed the count on real transcript."
)


def _fact(**over):
    base = {
        "content": "Distill proposals are capped at twenty because a higher threshold barely changed the count.",
        "evidence": "We decided to cap distill proposals at twenty",
        "context_type": "decision",
    }
    base.update(over)
    return base


def test_a_fact_whose_evidence_is_not_in_the_transcript_is_dropped():
    from marm_mcp_server.core.distill import _llm_usable

    invented = _fact(evidence="We agreed to cap proposals at fifty on Tuesday")
    assert _llm_usable(invented, TRANSCRIPT) is None


def test_a_fact_with_real_evidence_is_kept_and_carries_it():
    from marm_mcp_server.core.distill import _llm_usable

    candidate = _llm_usable(_fact(), TRANSCRIPT)
    assert candidate is not None
    assert candidate.context_type == "decision"
    assert candidate.evidence in TRANSCRIPT


def test_evidence_matching_ignores_whitespace_but_not_words():
    """Models re-wrap and re-indent when they copy, and that is not the failure
    this guard exists to catch."""
    from marm_mcp_server.core.distill import _llm_usable

    rewrapped = _fact(evidence="We   decided to cap\n  distill proposals at twenty")
    assert _llm_usable(rewrapped, TRANSCRIPT) is not None

    reworded = _fact(evidence="We chose to cap distill proposals at twenty")
    assert _llm_usable(reworded, TRANSCRIPT) is None


def test_a_generated_fact_may_not_open_on_a_dangling_pronoun():
    """Self-containment is the whole reason to generate rather than select."""
    from marm_mcp_server.core.distill import _llm_usable

    dangling = _fact(
        content="It is capped at twenty because a higher threshold changed little."
    )
    assert _llm_usable(dangling, TRANSCRIPT) is None


@pytest.mark.parametrize("missing", ["content", "evidence"])
def test_an_incomplete_fact_is_dropped(missing):
    from marm_mcp_server.core.distill import _llm_usable

    assert _llm_usable(_fact(**{missing: ""}), TRANSCRIPT) is None


def test_an_unknown_context_type_falls_back_rather_than_being_stored():
    from marm_mcp_server.core.distill import _llm_usable

    candidate = _llm_usable(_fact(context_type="wildly-invented"), TRANSCRIPT)
    assert candidate is not None
    assert candidate.context_type == "general"


def test_extraction_falls_back_to_selection_when_no_model_is_reachable(monkeypatch):
    """The generation path is an enhancement over a pipeline that works. A
    stopped container must not take the feature down with it."""
    from marm_mcp_server.core import distill as core
    from marm_mcp_server.services import local_llm

    monkeypatch.setattr(local_llm, "available", lambda *a, **k: None)
    assert core.llm_extract(TRANSCRIPT) is None


def test_a_model_that_returns_nonsense_falls_back_too(monkeypatch):
    from marm_mcp_server.core import distill as core
    from marm_mcp_server.services import local_llm

    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub")
    monkeypatch.setattr(local_llm, "complete_json", lambda *a, **k: None)
    assert core.llm_extract(TRANSCRIPT) is None


def test_an_object_wrapped_array_is_accepted(monkeypatch):
    """Some servers honour response_format by wrapping the array in an object;
    that is a shape difference, not a failure."""
    from marm_mcp_server.core import distill as core
    from marm_mcp_server.services import local_llm

    monkeypatch.setattr(local_llm, "available", lambda *a, **k: "stub")
    monkeypatch.setattr(
        local_llm, "complete_json", lambda *a, **k: {"facts": [_fact()]}
    )
    got = core.llm_extract(TRANSCRIPT)
    assert got and got[0].evidence


# --- review nudges ----------------------------------------------------------
#
# A staged proposal nobody is told about is a proposal nobody reviews. Seven
# generated proposals sat pending for hours on the live deployment because the
# only way to learn the queue was non-empty was to open the Console and look.


def _stage(
    memory,
    content,
    *,
    score=1.0,
    verdict="new",
    hours=168,
    nudges=0,
    status="pending",
    session="s",
):
    import uuid
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    row_id = str(uuid.uuid4())
    with memory.get_connection() as conn:
        conn.execute(
            "INSERT INTO distill_staging (id, session_name, content, score, reasons, "
            "verdict, cosine, neighbour_id, neighbour_content, status, candidate_hash, "
            "project, context_type, applied_memory_id, nudge_count, last_nudged_at, "
            "expires_at, created_at, updated_at, reviewed_at, evidence, mode) "
            "VALUES (?,?,?,?,'[]',?,0.9,NULL,'the stored one',?,?,NULL,'general',NULL,"
            "?,NULL,?,?,?,NULL,'','generated')",
            (
                row_id,
                session,
                content,
                score,
                verdict,
                status,
                row_id,
                nudges,
                (now + timedelta(hours=hours)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return row_id


@pytest.fixture()
def staged_memory(monkeypatch, tmp_path):
    from conftest import load_isolated_server

    assert load_isolated_server(monkeypatch, tmp_path) is not None
    from marm_mcp_server.core.memory import memory as live

    return live


def test_a_pending_proposal_asks_to_be_reviewed(staged_memory):
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    proposal_id = _stage(staged_memory, "The daemon reparents to systemd.")
    block = claim_pending_distill_prompt(staged_memory)

    assert block is not None, "a pending proposal produced no review request"
    text = block["text"]
    assert proposal_id in text
    # Both decisions, spelled as calls the agent can make verbatim.
    assert 'action="apply"' in text
    assert 'action="discard"' in text


def test_a_near_verdict_carries_the_memory_it_resembles(staged_memory):
    """The whole reason a `near` needs a human: an encoder cannot tell
    "refines" from "contradicts", so the comparison has to be in the ask."""
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    _stage(staged_memory, "A restatement.", verdict="near")
    text = claim_pending_distill_prompt(staged_memory)["text"]

    assert "the stored one" in text
    assert "contradicts" in text


def test_only_one_review_is_asked_for_per_window(staged_memory):
    """The cooldown is GLOBAL, not per proposal.

    A distil run stages a batch. A per-row cooldown would then put a review
    request on N consecutive tool responses, which is the terminal noise
    agents already get complained about.
    """
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    for i in range(5):
        _stage(
            staged_memory,
            f"Proposal {i} about something durable.",
            score=1.0 - i * 0.01,
        )

    asked = [bool(claim_pending_distill_prompt(staged_memory)) for _ in range(5)]
    assert asked.count(True) == 1, asked


def test_the_best_proposal_is_asked_about_first(staged_memory):
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    _stage(staged_memory, "A weak one.", score=0.3)
    _stage(staged_memory, "The strongest one.", score=1.4)
    text = claim_pending_distill_prompt(staged_memory)["text"]

    assert "The strongest one." in text


def test_an_expired_proposal_is_swept_rather_than_asked_about(staged_memory):
    """`review` already filtered these out, so without the sweep they were a
    slow leak: invisible and permanent."""
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    expired = _stage(staged_memory, "Nobody ever looked at this.", hours=-1)
    assert claim_pending_distill_prompt(staged_memory) is None

    with staged_memory.get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM distill_staging WHERE id = ?", (expired,)
        ).fetchone()[0]
    assert status == "stale"


def test_a_queue_nobody_answers_stops_asking(staged_memory):
    """Otherwise it nags forever, which is how the channel stops being read."""
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    ignored = _stage(staged_memory, "Asked about three times already.", nudges=3)
    assert claim_pending_distill_prompt(staged_memory) is None

    with staged_memory.get_connection() as conn:
        status = conn.execute(
            "SELECT status FROM distill_staging WHERE id = ?", (ignored,)
        ).fetchone()[0]
    assert status == "nudge_exhausted"


def test_nothing_pending_asks_nothing(staged_memory):
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    assert claim_pending_distill_prompt(staged_memory) is None


def test_the_nudge_can_be_turned_off(staged_memory, monkeypatch):
    from marm_mcp_server.config import settings
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    _stage(staged_memory, "Something durable.")
    monkeypatch.setattr(settings, "DISTILL_NUDGE_ENABLED", False)
    assert claim_pending_distill_prompt(staged_memory) is None


@pytest.mark.asyncio
async def test_a_queued_write_carries_the_project_column(tmp_path):
    """`metadata["project"]` is not the `project` column.

    Project-filtered recall and code-context read the column, so a proposal
    applied with `project=...` was landing unscoped: `store_memory_queued` did
    not forward the scope, and `_store_memory` fell back to `MARM_PROJECT`.
    """
    from marm_mcp_server.core.memory import MARMMemory

    mem = MARMMemory(str(tmp_path / "memory.db"))
    mem._encoder_failed = True

    scoped = await mem.store_memory_queued(
        "a fact worth keeping",
        "sess",
        "general",
        {"source": "marm_distill"},
        queue_enabled=False,
        project="scoped-project",
        explicit_scope=True,
    )
    unscoped = await mem.store_memory_queued(
        "another fact", "sess", "general", {}, queue_enabled=False
    )

    with mem.get_connection() as conn:
        rows = dict(
            conn.execute(
                "SELECT id, project FROM memories WHERE id IN (?, ?)",
                (scoped, unscoped),
            ).fetchall()
        )
    assert rows[scoped] == "scoped-project"
    assert rows[unscoped] != "scoped-project"


def test_the_same_content_can_be_proposed_for_a_different_project(staged):
    """`project` is part of proposal identity, not just a stored attribute.

    The unique `candidate_hash` index with INSERT OR IGNORE means a hash that
    omits the project silently suppresses the same fact for another project in
    the same session -- including after the first was discarded, so a project
    could never be offered something another had rejected.
    """
    service, live = staged

    first = _propose(service, live, POSITIVES[1], project="alpha")
    assert first["proposals"], "the first project must get a proposal"
    service.discard(live, first["proposals"][0]["id"])

    second = _propose(service, live, POSITIVES[1], project="beta")
    assert second["proposals"], (
        "a second project must still be offered content the first discarded"
    )
    assert second["proposals"][0]["id"] != first["proposals"][0]["id"]


def test_an_apply_interrupted_after_the_write_is_recovered_not_stranded(staged):
    """A crash between the memory write and the staging update must be
    recoverable.

    The two live in separate transactions, so the memory can be committed while
    the proposal is still `applying`. Nothing else reads that status -- apply
    rejected it, discard and review skip it -- so the proposal was stranded
    forever and its memory orphaned from its own bookkeeping.
    """
    import asyncio

    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]
    assert asyncio.run(service.apply(live, proposal_id))["status"] == "success"

    # Rewind exactly what a crash would have left: the memory is committed, the
    # staging row never made it past `applying`.
    with live.get_connection() as conn:
        conn.execute(
            "UPDATE distill_staging SET status = 'applying', "
            "applied_memory_id = NULL WHERE id = ?",
            (proposal_id,),
        )

    recovered = asyncio.run(service.apply(live, proposal_id))
    assert recovered["status"] == "success", recovered
    assert recovered.get("recovered") is True
    assert recovered["memory_id"], "it must report the memory that was already written"

    with live.get_connection() as conn:
        status, memory_id = conn.execute(
            "SELECT status, applied_memory_id FROM distill_staging WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    assert status == "applied"
    assert memory_id == recovered["memory_id"]


def test_a_stale_applying_row_with_no_memory_is_retried_not_recovered(staged):
    """The mirror case: decide from the store, not from the status.

    If the write never landed there is nothing to recover, and treating the row
    as applied would claim a memory that does not exist. The claim is backdated
    so it reads as abandoned rather than in flight.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]
    long_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with live.get_connection() as conn:
        conn.execute(
            "UPDATE distill_staging SET status = 'applying', updated_at = ? "
            "WHERE id = ?",
            (long_ago, proposal_id),
        )

    result = asyncio.run(service.apply(live, proposal_id))
    assert result["status"] == "success"
    assert result.get("recovered") is not True, "nothing was there to recover"
    assert result["memory_id"]


def test_a_fresh_applying_claim_is_not_stolen_from_a_write_in_flight(staged):
    """Recovery must not become a second writer.

    An `applying` row with no memory yet is EITHER a crash before the write
    landed OR an apply still running. Taking over the second case enqueues a
    second write for the same proposal -- the duplicate this service exists to
    prevent -- so only a claim old enough to be abandoned may be recovered.
    """
    import asyncio

    service, live = staged
    proposal_id = _propose(service, live, POSITIVES[1])["proposals"][0]["id"]
    with live.get_connection() as conn:
        conn.execute(
            "UPDATE distill_staging SET status = 'applying', updated_at = ? "
            "WHERE id = ?",
            (_now_iso(), proposal_id),
        )

    result = asyncio.run(service.apply(live, proposal_id))
    assert result["status"] == "error"
    assert "already applying" in result["error"]

    with live.get_connection() as conn:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM memories "
            "WHERE json_extract(metadata, '$.proposal_id') = ?",
            (proposal_id,),
        ).fetchone()
    assert count == 0, "refusing the claim must not have written a memory"


def test_a_long_neighbour_cannot_crowd_out_the_proposal(staged_memory):
    """The text under review must survive truncation.

    `neighbour_content` has no length constraint while the write path accepts
    10,000 characters, and `_truncate` keeps the prefix -- so with the neighbour
    rendered above it, a long enough neighbour kept the apply/discard
    instructions and cut away the proposal itself.
    """
    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    content = "The proposal that has to survive."
    _stage(staged_memory, content, verdict="near")
    with staged_memory.get_connection() as conn:
        conn.execute("UPDATE distill_staging SET neighbour_content = ?", ("N" * 9000,))

    text = claim_pending_distill_prompt(staged_memory)["text"]
    assert "Proposal:" in text, "the proposal heading was truncated away"
    assert content[:60] in text, "the proposal text itself was truncated away"


def test_scope_identity_is_case_sensitive(staged):
    """`compute_content_hash` normalises; a session or project name must not be.

    It lowercases and strips its whole input, so folding the scope through it
    made `Alpha` and `alpha` one proposal -- and `INSERT OR IGNORE` on the
    unique index then dropped one of two legitimately distinct ones.
    """
    service, live = staged

    lower = _propose(service, live, POSITIVES[1], project="alpha")
    upper = _propose(service, live, POSITIVES[1], project="Alpha")

    # `proposals` lists a suppressed record too, with staged=False -- so the
    # presence of the entry proves nothing. `staged` is the signal.
    assert lower["proposals"][0]["staged"] is True
    assert upper["proposals"][0]["staged"] is True, (
        "a project differing only in case is a different scope, and must not be "
        "suppressed by the unique candidate_hash index"
    )
    assert upper["proposals"][0]["id"] != lower["proposals"][0]["id"]


def test_an_expired_nudge_exhausted_proposal_is_swept(staged_memory):
    """The queue giving up on a proposal is not the proposal being resolved.

    The sweep only touched `pending`, so an expired `nudge_exhausted` row was
    hidden by review() and never cleaned up -- unbounded growth in staging.
    """
    from datetime import datetime, timedelta, timezone

    from marm_mcp_server.services.distill import claim_pending_distill_prompt

    _stage(staged_memory, "Exhausted and expired.", status="nudge_exhausted")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with staged_memory.get_connection() as conn:
        conn.execute("UPDATE distill_staging SET expires_at = ?", (past,))

    claim_pending_distill_prompt(staged_memory)

    with staged_memory.get_connection() as conn:
        (status,) = conn.execute("SELECT status FROM distill_staging").fetchone()
    assert status == "stale", f"expired nudge_exhausted row was left as {status}"


@pytest.mark.asyncio
async def test_evidence_quoted_from_a_stored_memory_is_a_duplicate():
    """Regression, from the real Grok-Bot queue.

    Both of these resolved `new` -- at 0.800 and 0.801, just under NEAR_AT --
    while the store already contained the sentence verbatim. The paragraph
    they were extracted from is long, so its embedding is dominated by
    everything else it says, and the generated content paraphrases the span
    ("SQL and sshd_config" for "SQL/sshd_config") so it misses on the surface
    too. The evidence span is the thing that matches exactly.
    """
    paragraph = (
        "MARM 2.48.2 is healthy with connected SQLite, semantic search and "
        "concept extraction. Grok-Bot full code graph is ready with 4,417 "
        "nodes and 22,375 edges. Twelve SQL/sshd_config files have "
        "best-effort partial parse ranges; use lexical lookup for those "
        "ranges. No source files or Git state were changed."
    )
    stub = _StubMemory(neighbours=[{"id": "m1", "content": paragraph, "cosine": 0.801}])
    (only,) = await resolve(
        stub,
        [
            Candidate(
                "Twelve SQL and sshd_config files have best-effort partial "
                "parse ranges requiring lexical lookup.",
                1.0,
                (),
                evidence=(
                    "Twelve SQL/sshd_config files have best-effort partial "
                    "parse ranges; use lexical lookup for those ranges."
                ),
            )
        ],
    )
    assert only.verdict == "duplicate"
    assert only.neighbour_id == "m1"
    assert only.neighbour_content == paragraph


@pytest.mark.asyncio
async def test_containment_needs_a_span_long_enough_to_be_a_memory():
    """A short span must not match half the store.

    `MIN_LENGTH` is the floor rather than a second constant: it is already the
    length below which a span is too slight to be a memory.
    """
    stub = _StubMemory(
        neighbours=[
            {
                "id": "m1",
                "content": "the graph daemon reparents to systemd",
                "cosine": 0.4,
            }
        ]
    )
    (only,) = await resolve(
        stub,
        [Candidate("a wholly novel fact", 1.0, (), evidence="to systemd")],
    )
    assert only.verdict == "new"
