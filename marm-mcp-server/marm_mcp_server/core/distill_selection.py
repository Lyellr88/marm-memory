from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from spacy.language import Language
    from spacy.tokens import Doc, Span

# A sentence earning its place usually explains rather than reports. These are
# the shapes that carry a reason, a cause, or a decision.
_REASON = re.compile(
    r"\b(because|since|so that|turns out|turned out|the cause|root cause|"
    r"which means|rather than|instead of|otherwise|the reason|due to|"
    r"fixed by|caused by|resolved by|thanks to|in order to)\b",
    re.I,
)
_DECISION = re.compile(
    r"\b(decided|chose|chosen|settled on|we use|uses|must|never|always|"
    r"deliberately|intentionally|on purpose|by design|prefer|preferred)\b",
    re.I,
)
_FINDING = re.compile(
    r"\b(found|discovered|measured|verified|confirmed|observed|reproduced|"
    r"turns out|produces|produced|returns|fails|failed|breaks|broke)\b",
    re.I,
)

# Conversation, not record. A memory beginning "It does that because..." cannot
# be read six months later: the antecedent is gone with the transcript.
_DANGLING_START = re.compile(r"^(it|this|that|these|those|they|he|she|there)\b", re.I)
_CHATTY = re.compile(
    r"\b(i|i'm|i've|i'll|you|you're|we'll|let's|please|thanks|ok|okay)\b", re.I
)
# A correction is the most valuable thing in this store, and it usually says
# what something is NOT.
_CONTRAST = re.compile(
    r"(\bnot\b|\bnever\b|\brather than\b|\binstead of\b|\bcannot\b|"
    r"\bdoes not\b|\bdo not\b|\bwithout\b|\bno longer\b)",
    re.I,
)
# The closed class itself. Anything else tagged PRON is a tagger error.
_PRONOUNS = frozenset(
    """i me my mine myself you your yours yourself yourselves he him his himself
    she her hers herself it its itself we us our ours ourselves they them their
    theirs themselves this that these those there who whom whose which what
    someone somebody something anyone anybody anything everyone everybody
    everything no one nobody nothing one ones""".split()
)

_HEDGE = re.compile(
    r"\b(maybe|probably|might|could be|i think|i guess|perhaps|seems like|not sure)\b",
    re.I,
)

# A code-shaped token is evidence of a concrete subject: dotted paths, snake or
# camel identifiers, file names, flags.
_CODE_SHAPED = re.compile(
    r"(\w+\.\w+[\w.]*|\w+_\w+|[a-z]+[A-Z]\w*|--?[a-z][\w-]+|`[^`]+`|/\w+[/\w.]*)"
)


def _shape_score(doc_or_span: "Doc | Span") -> tuple[float, list[str]]:
    """Score a parsed sentence on whether it reads like a durable MARM memory.

    Structure first, keywords second -- and that ordering was a correction, not
    a preference. The first version scored on keyword lists ("because", "so
    that", "decided") and was calibrated against the live store: the eight
    MARM-Stack memories, which are the canonical headline shape, scored +0.00
    to +0.20 and NOT ONE cleared the threshold. "marm-ctx weights call-graph
    edges by resolver strategy, not confidence alone" is exactly what this
    should propose, and the keyword scorer rejected it.

    The reason is that a MARM memory is a terse assertion, not an argument. The
    "why" lives in metadata, so a good memory frequently contains no causal
    word at all. What it does contain is a NAMED subject, an indicative verb,
    and something specific said about that subject -- which is the dependency
    parse, not a word list.

    Additive with explicit reasons rather than one opaque number, because a
    reviewer deciding whether to keep a proposal is owed the argument for it.
    """
    text = doc_or_span.text if hasattr(doc_or_span, "text") else str(doc_or_span)
    score = 0.0
    reasons: list[str] = []

    tokens = [t for t in doc_or_span if not t.is_space]
    subjects = [t for t in tokens if t.dep_ in {"nsubj", "nsubjpass"}]
    root = next((t for t in tokens if t.dep_ == "ROOT"), None)

    # A named subject is the single strongest signal. "The code-graph daemon",
    # "marm_delete", "An MCP server" -- something a reader can look up.
    if subjects:
        subject = subjects[0]
        # A bare pronoun subject is the opposite of a named one: "that works
        # for me" has a subject and says nothing retrievable. Rewarding it the
        # same as "the code-graph daemon" put chatter level with real memories.
        #
        # The membership test is LEXICAL, and that is not belt-and-braces. A
        # pronoun is a closed class, so a token tagged PRON that is not one of
        # these words is a mistag -- and the model makes exactly that mistake on
        # this domain's identifiers, which would otherwise turn a bonus into a
        # penalty and sink a real memory.
        if subject.lower_ in _PRONOUNS:
            score -= 0.25
            reasons.append("subject is a bare pronoun")
        else:
            named = (
                subject.pos_ == "PROPN"
                or bool(_CODE_SHAPED.search(subject.text))
                or any(child.dep_ == "compound" for child in subject.children)
            )
            score += 0.35 if named else 0.15
            reasons.append("names its subject" if named else "has a subject")

    # An indicative verb in present or past. A memory states; it does not
    # speculate, and modal-only sentences ("should", "could") are proposals.
    if root is not None and root.pos_ in {"VERB", "AUX"}:
        if root.tag_ in {"VBZ", "VBP", "VBD", "VBN"}:
            score += 0.25
            reasons.append("states rather than speculates")
        elif root.tag_ == "MD":
            score -= 0.10
            reasons.append("modal, not a statement of fact")

    # Says something specific about the subject rather than merely existing.
    if any(
        t.dep_ in {"dobj", "attr", "acomp", "oprd", "pobj", "xcomp"} for t in tokens
    ):
        score += 0.20
        reasons.append("says something specific")

    # Contrast is characteristic of a correction, and corrections are the most
    # valuable thing in this store: "not confidence alone", "rather than".
    if _CONTRAST.search(text):
        score += 0.15
        reasons.append("draws a contrast")

    # Keyword signals stay, demoted to bonuses. They are real when present and
    # were simply never the backbone.
    if _REASON.search(text):
        score += 0.15
        reasons.append("explains why")
    if _DECISION.search(text):
        score += 0.10
        reasons.append("states a decision")
    if _FINDING.search(text):
        score += 0.10
        reasons.append("reports a finding")

    code_hits = len(_CODE_SHAPED.findall(text))
    if code_hits:
        score += min(0.15, 0.05 * code_hits)
        reasons.append("names something concrete")

    # Penalties, unchanged: calibration showed these rejected exactly what they
    # should -- chatter, imperatives, questions, hedges, dangling pronouns.
    if _DANGLING_START.match(text.strip()):
        score -= 0.45
        reasons.append("opens on an unresolvable pronoun")
    if _CHATTY.search(text):
        score -= 0.35
        reasons.append("conversational")
    if _HEDGE.search(text):
        score -= 0.30
        reasons.append("hedged")
    if text.rstrip().endswith("?"):
        score -= 0.50
        reasons.append("a question")

    return score, reasons


def _normalise(text: str) -> str:
    """One line, no markdown furniture, no trailing punctuation noise."""
    collapsed = " ".join(text.split())
    # A COMPLETE list marker, not a character class. The class matched bare
    # digits, so a sentence opening with a number lost it: "404 responses are
    # retried" was stored as "responses are retried", and a date opening a
    # sentence went the same way. A memory that has lost its number still
    # reads like a fact, which is what makes it worse than no memory at all.
    collapsed = re.sub(r"^\s*(?:[-*\u2022#>]+\s+|\d+[.)]\s+)", "", collapsed)
    # Emphasis markers survive segmentation and would be stored verbatim.
    # Backticks are deliberately KEPT: `marm_delete` reads as an identifier and
    # a memory that loses them reads as prose about a word.
    collapsed = re.sub(r"\*\*|__|(?<!\*)\*(?!\*)", "", collapsed)
    return collapsed.strip().rstrip(",;:")


def _dedupe_key(content: str) -> str:
    """Collapse to letters and digits so two spellings of one sentence agree.

    One sentence can appear twice in a transcript differing only in backticks
    or punctuation; stripping those is what makes them one proposal.

    Case is PRESERVED. Folding it also merged sentences about `Foo` and `foo`,
    and in this domain those are two identifiers rather than two spellings.
    The asymmetry decides it: a near-duplicate that survives is shown to a
    reviewer with a `duplicate` verdict, while a distinct fact dropped here is
    never proposed at all.
    """
    return re.sub(r"[^A-Za-z0-9]+", "", content)


def _demarkdown(text: str) -> str:
    """Flatten markdown enough that sentence segmentation is not lied to.

    A heading carries no terminal punctuation, so spaCy runs it straight into
    the paragraph beneath it and emits one span that is a title welded to an
    unrelated clause. Giving each heading a full stop costs nothing and keeps
    the heading available as a candidate in its own right.
    """
    # Code blocks are transcript, not statement, and they wreck segmentation.
    out = re.sub(r"```.*?```", " ", text, flags=re.S)
    lines = []
    for line in out.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        leading = len(body) - len(body.lstrip())
        if leading > 3:
            lines.append(line)
            continue
        remainder = body[leading:]
        hashes = len(remainder) - len(remainder.lstrip("#"))
        heading = remainder[hashes:].strip()
        if 1 <= hashes <= 6 and heading:
            lines.append(f"{heading}.{ending}")
        else:
            lines.append(line)
    return "".join(lines)


def _usable(span: "Span") -> bool:
    """Reject spans that cannot become a standalone memory.

    An imperative ("run the tests") is an instruction, not a record, and spaCy
    marks it by putting a base-form verb first with no subject.

    It deliberately does NOT require a VERB or AUX tag. `en_core_web_sm` does
    not know this domain's verbs and tags several of them as nouns -- it reads
    "marm-ctx weights call-graph edges" as a compound noun phrase, and
    "reparents" likewise. Requiring a verb threw out the single best example
    this feature exists to capture, so the gate is now structural (there is a
    root, and it is not an imperative) and quality is left to the score.
    """
    text = span.text.strip()
    if not text:
        return False
    tokens = [t for t in span if not t.is_space]
    if len(tokens) < 4:
        return False
    first = tokens[0]
    # The imperative guard must not fire on an identifier. spaCy splits
    # `marm-ctx` into `marm` / `-` / `ctx` and tags the leading `marm` as VB,
    # so "marm-ctx weights call-graph edges by resolver strategy" read as a
    # command and was thrown out -- the single best example this feature
    # exists to capture. A first token glued to a hyphen, underscore or dot is
    # part of a name, not a verb.
    glued = (
        first.whitespace_ == ""
        and len(tokens) > 1
        and tokens[1].text in {"-", "_", "."}
    )
    if first.tag_ == "VB" and not glued:
        if not any(t.dep_ in {"nsubj", "nsubjpass"} for t in span):
            return False
    return any(t.dep_ == "ROOT" for t in tokens)


def _reparse(nlp: "Language", content: str, fallback: "Span") -> "Doc | Span":
    """Parse one candidate on its own, so its score is its own property.

    Segmentation needs the whole document, but scoring must not depend on it.
    The same sentence scored +0.85 alone and +0.25 when the line above it was a
    question, because the tagger carried that context across the boundary. A
    memory's quality cannot depend on what was said before it.

    Falls back to the in-document span if the standalone parse does not come
    back as a single sentence, which would mean re-parsing changed the very
    boundary being scored.
    """
    try:
        document = nlp(content)
    except Exception:  # pragma: no cover - defensive; the parser is in-process
        return fallback
    sentences = list(document.sents)
    return sentences[0] if len(sentences) == 1 else fallback
