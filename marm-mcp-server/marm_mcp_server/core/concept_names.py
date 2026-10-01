"""What a concept's name says that its embedding cannot.

A text embedding scores names by broad meaning, so `v2.1.0` and `v2.0.0`, or
`first` and `second`, land above 0.9 of each other. Names whose numbers differ
name different things, however close their vectors are.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter

_NUMBER = re.compile(r"\d+(?:\.\d+)*")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_WORD = re.compile(r"[A-Za-z]+")

_UNITS = """_ _ two three four five six seven eight nine ten eleven twelve thirteen
    fourteen fifteen sixteen seventeen eighteen nineteen""".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORDINALS = """_ first second third fourth fifth sixth seventh eighth ninth tenth
    eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth
    eighteenth nineteenth""".split()
_TENTHS = """_ _ twentieth thirtieth fortieth fiftieth sixtieth seventieth
    eightieth ninetieth""".split()

# Not "one" or "zero": "the real one" is a pronoun far more often than a count.
_NUMBER_WORDS = {
    word: value * scale
    for scale, words in ((1, _UNITS), (10, _TENS), (1, _ORDINALS), (10, _TENTHS))
    for value, word in enumerate(words)
    if word != "_"
}
_TENS_WORDS = frozenset(_TENS[2:])
_ONES = {
    **{w: v for w, v in _NUMBER_WORDS.items() if 0 < v < 10},
    "one": 1,
}
# Spoken forms these rules do not compose; such a name has no reliable number.
_UNREAD = frozenset("hundred hundredth thousand thousandth million billion".split())
# After a count, "second" may be a unit of time rather than an ordinal.
_AFTER_COUNT = re.compile(r"(?:\d|\b(?:%s))[\s-]+$" % "|".join(_TENS[2:]), re.I)


def _normalise(run: str) -> str:
    head, *rest = run.split(".")
    head = head.lstrip("0") or "0"
    if len(rest) == 1:
        # 100 and 100.00 are one value; 2.10 and 2.1 are two releases.
        return head if not rest[0].strip("0") else f"{head}.{rest[0]}"
    return ".".join([head, *(part.lstrip("0") or "0" for part in rest)])


def _digits(name: str) -> tuple[str, ...]:
    return tuple(
        sorted(_normalise(run) for run in _NUMBER.findall(_THOUSANDS.sub("", name)))
    )


def _readings(name: str) -> set[tuple[str, ...]] | None:
    """Every way the name's numbers can be read, or None when a number word
    is one these rules cannot compose."""
    words = list(_WORD.finditer(name))
    if any(w.group().casefold() in _UNREAD for w in words):
        return None
    # One entry per number in the name: the readings it allows.
    options: list[list[tuple[str, ...]]] = []
    i = 0
    while i < len(words):
        word = words[i].group().casefold()
        value = _NUMBER_WORDS.get(word)
        # After a count, "second" may be a unit of time, which adds no number.
        if word == "second" and _AFTER_COUNT.search(name[: words[i].start()]):
            options.append([("2",), ()])
            i += 1
            continue
        if value is not None and word in _TENS_WORDS and i + 1 < len(words):
            nxt = words[i + 1]
            gap = name[words[i].end() : nxt.start()]
            follower = nxt.group().casefold()
            ones = _ONES.get(follower)
            if ones is not None and not gap.strip(" -"):
                composed = (str(value + ones),)
                duration = (str(value),)
                options.append(
                    [composed, duration] if follower == "second" else [composed]
                )
                i += 2
                continue
        if value is not None:
            options.append([(str(value),)])
        i += 1
    digits = _digits(name)
    return {
        tuple(sorted(digits + sum(combo, ()))) for combo in itertools.product(*options)
    }


def number_signature(name: str) -> tuple[str, ...] | None:
    """The numbers a name carries, in digits or words, order-free.

    None when they cannot be read one way only.
    """
    readings = _readings(name)
    if readings is None or len(readings) != 1:
        return None
    return next(iter(readings))


def numbers_differ(a: str, b: str) -> bool:
    """Whether two names carry different numbers, so cannot be one entity."""
    read_a, read_b = _readings(a), _readings(b)
    if read_a is not None and read_b is not None:
        return not read_a & read_b
    # Where a number word cannot be read, only the digits are known, and they
    # may belong to that word's number: differ only if no reading of either
    # side fits inside one of the other's.
    known_a = (
        [Counter(r) for r in read_a] if read_a is not None else [Counter(_digits(a))]
    )
    known_b = (
        [Counter(r) for r in read_b] if read_b is not None else [Counter(_digits(b))]
    )
    return not any(x <= y or y <= x for x in known_a for y in known_b)
