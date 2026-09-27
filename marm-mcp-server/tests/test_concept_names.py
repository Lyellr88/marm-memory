import pytest

from marm_mcp_server.core.concept_names import number_signature, numbers_differ


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("v2.1.0", "v2.0.0"),
        ("L-1.3", "L-1.4"),
        ("K62", "K61"),
        ("R-4.6", "R-5.2"),
        ("1.98.1", "2.36"),
        ("first", "second"),
        ("second", "Third"),
        ("seven-day", "day"),
        ("NTFS", "ntfs3"),
    ],
)
def test_names_whose_numbers_differ_are_different_things(a, b):
    assert numbers_differ(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("fix", "the fix"),
        ("100%", "100.00%"),
        ("the Cloud Key Gen2 Plus", "the Cloud Key Gen2"),
        # "one" is a pronoun far more often than a number: a real merge.
        ("the real ones", "the real one"),
        ("v2.0", "version 2.0"),
        ("PRs", "PR"),
        ("1,000 rows", "1000 rows"),
    ],
)
def test_names_with_the_same_numbers_are_left_to_the_similarity(a, b):
    assert not numbers_differ(a, b)


def test_the_signature_ignores_order_and_leading_zeros():
    assert number_signature("rev 07 of 2026") == number_signature("2026, rev 7")
