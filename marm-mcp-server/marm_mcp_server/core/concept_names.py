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

# Not "one" or "zero": "the real one" is a pronoun far more often than a count.
_NUMBER_WORDS = {
    word: str(value)
    for value, word in enumerate(
        "_ _ two three four five six seven eight nine ten eleven twelve".split()
    )
    if word != "_"
}
_NUMBER_WORDS.update(
    {
        word: str(value)
        for value, word in enumerate(
            "first second third fourth fifth sixth seventh eighth ninth tenth".split(),
            start=1,
        )
    }
)


def _normalise(run: str) -> str:
    parts = run.split(".")
    if len(parts) <= 2:
        # A number, not a version: 100 and 100.00 are one value.
        return repr(float(".".join(parts)))
    return ".".join(str(int(part)) for part in parts)


def number_signature(name: str) -> tuple[str, ...]:
    """The numbers a name carries, in digits or words, order-free."""
    found = [_normalise(run) for run in _NUMBER.findall(_THOUSANDS.sub("", name))]
    found += [
        _NUMBER_WORDS[word.casefold()]
        for word in _WORD.findall(name)
        if word.casefold() in _NUMBER_WORDS
    ]
    return tuple(sorted(found))


def numbers_differ(a: str, b: str) -> bool:
    """Whether two names carry different numbers, so cannot be one entity."""
    sig_a, sig_b = number_signature(a), number_signature(b)
    return bool(sig_a or sig_b) and sig_a != sig_b
