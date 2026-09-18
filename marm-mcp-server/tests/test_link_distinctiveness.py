"""Tests for the distinctiveness gate on memory->code symbol linking.

The first test is the one that matters: every link the ungated engine produced
on a 31,452-node repository was a false positive, and those exact names are the
regression corpus. If one of them starts passing again, the gate has drifted.
"""

import ast
import collections
import pathlib

import pytest

from marm_mcp_server.core import _link_distinctiveness as gate

_GATE_SOURCE = pathlib.Path(gate.__file__)


# The six links observed before the gate existed. None was about the symbol it
# matched; see the module docstring in gate.py.
OBSERVED_FALSE_POSITIVES = [
    "upload",
    "update",
    "toml",
    "actions",
    "updates",
    "criterion",
]


@pytest.mark.parametrize("name", OBSERVED_FALSE_POSITIVES)
def test_observed_false_positives_are_rejected(name):
    assert gate.is_linkable(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "update_state",  # snake_case
        "UpdateState",  # PascalCase
        "updateState",  # camelCase
        "Foo::bar",  # qualified
        "marm_ctx.compose",  # dotted
    ],
)
def test_identifier_shapes_are_accepted(name):
    """Identifier shape is positive evidence and outranks the stoplist."""
    assert gate.is_linkable(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "0.15",
        "11",
        "2.0",
        "0.5→0.8",
        "v1.8.2",
        "V2",
        "1-2-3",
    ],
)
def test_version_and_numeric_strings_are_rejected(name):
    assert gate.is_linkable(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "11 Open PRs",
        "48 Cargo.toml Files Across Project Structure",
        "some thing",
    ],
)
def test_multi_token_fragments_are_rejected(name):
    """A symbol reference is one token; the extractor keeps fragments whole."""
    assert gate.is_linkable(name) is False


@pytest.mark.parametrize("name", ["", "  ", "ab", "a"])
def test_too_short_or_empty_is_rejected(name):
    assert gate.is_linkable(name) is False


@pytest.mark.parametrize("bad", [None, 42, [], {}])
def test_non_string_is_rejected(bad):
    assert gate.is_linkable(bad) is False


@pytest.mark.parametrize("name", ["__update__", "_update", "update_", "update."])
def test_underscored_common_word_is_accepted_as_shape(name):
    """Pins a subtlety worth knowing before editing the gate.

    `_CODE_SHAPED` matches on any `_` or `.`, and shape is checked BEFORE the
    stoplist, so `_update` links even though `update` does not. That is
    defensible -- `_update` really is an identifier where `update` is a word --
    but it means nothing containing an underscore ever reaches the stoplist.

    The gate used to end in `casefold().strip("_") not in _COMMON`, which read
    as protection against `__update__` and was in fact unreachable: any name
    with an underscore had already returned True, and stripping one without is
    a no-op. The strip is gone; this test pins the behaviour it implied but
    never delivered, so nobody re-adds it believing it does something.
    """
    assert gate.is_linkable(name) is True
    assert gate.is_linkable(name.strip("_.")) is False


@pytest.mark.parametrize(
    "label,expected",
    [
        ("section", False),
        ("folder", False),
        ("file", False),
        ("project", False),
        ("branch", False),
        ("module", False),
        ("Folder", False),
        ("  FILE  ", False),  # case/space insensitive
        ("function", True),
        ("class", True),
        ("method", True),
        ("", True),
        ("   ", True),
        (None, True),  # unlabelled: name gate decides
    ],
)
def test_is_symbol_label(label, expected):
    assert gate.is_symbol_label(label) is expected


def _stoplist_literals():
    """Read the set literal from source: a runtime set has already deduplicated."""
    tree = ast.parse(_GATE_SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Set) and len(node.elts) > 50:
            return [e.value for e in node.elts if isinstance(e, ast.Constant)]
    raise AssertionError("stoplist set literal not found")


def test_stoplist_has_no_duplicate_literals():
    """A duplicate is invisible at runtime but means a word was typed twice --
    and usually that the word actually intended is missing."""
    dupes = [w for w, c in collections.Counter(_stoplist_literals()).items() if c > 1]
    assert dupes == [], f"duplicate stoplist entries: {dupes}"


def test_stoplist_entries_are_normalised():
    """Lookup is `text.casefold().strip('_')`, so an entry that is not already
    lowercase and stripped can never match anything."""
    odd = [
        w for w in _stoplist_literals() if w != w.casefold().strip().strip("_") or not w
    ]
    assert odd == [], f"entries that can never match: {odd}"
