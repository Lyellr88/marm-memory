"""What a concept's name says that its embedding cannot.

A text embedding scores names by broad meaning, so `v2.1.0` and `v2.0.0`, or
`first` and `second`, land above 0.9 of each other. Names whose numbers differ
name different things, however close their vectors are.
"""

from __future__ import annotations

import re

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


def _normalise(run: str) -> str:
    head, *rest = run.split(".")
    head = head.lstrip("0") or "0"
    if len(rest) == 1:
        # 100 and 100.00 are one value; 2.10 and 2.1 are two releases.
        return head if not rest[0].strip("0") else f"{head}.{rest[0]}"
    return ".".join([head, *(part.lstrip("0") or "0" for part in rest)])


def _word_numbers(name: str) -> list[str] | None:
    words = list(_WORD.finditer(name))
    found: list[str] = []
    i = 0
    while i < len(words):
        word = words[i].group().casefold()
        if word in _UNREAD:
            return None
        value = _NUMBER_WORDS.get(word)
        if value is not None and word in _TENS_WORDS and i + 1 < len(words):
            nxt = words[i + 1]
            gap = name[words[i].end() : nxt.start()]
            ones = _ONES.get(nxt.group().casefold())
            if ones is not None and not gap.strip(" -"):
                value += ones
                i += 1
        if value is not None:
            found.append(str(value))
        i += 1
    return found


def number_signature(name: str) -> tuple[str, ...] | None:
    """The numbers a name carries, in digits or words, order-free.

    None when it spells a number these rules cannot read.
    """
    words = _word_numbers(name)
    if words is None:
        return None
    found = [_normalise(run) for run in _NUMBER.findall(_THOUSANDS.sub("", name))]
    return tuple(sorted(found + words))


def numbers_differ(a: str, b: str) -> bool:
    """Whether two names carry different numbers, so cannot be one entity."""
    sig_a, sig_b = number_signature(a), number_signature(b)
    if sig_a is None or sig_b is None:
        return False
    return bool(sig_a or sig_b) and sig_a != sig_b
