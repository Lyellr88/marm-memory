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
        ("v2.10", "v2.1"),
        ("0.05 mg", "0.5 mg"),
        ("id 9007199254740992", "id 9007199254740993"),
        ("the nineteenth", "the twentieth"),
        ("thirteen steps", "fourteen steps"),
        ("eleventh hour", "twelfth hour"),
        ("Phase twenty one", "Phase twenty two"),
        ("Phase twenty one", "Phase 20"),
        ("twenty-first", "twenty-second"),
        ("thirty seven", "thirty"),
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
        ("Phase 2", "Phase two"),
        ("first", "1"),
        ("the twentieth", "20"),
        ("v2", "v2.0"),
        ("Phase twenty one", "Phase 21"),
        ("Phase twenty-one", "Phase 21"),
        ("Phase twenty first", "Phase 21st"),
        ("Phase twenty first", "Phase 21"),
        ("Phase Twenty-First", "Phase 21"),
        ("ninety nine steps", "99 steps"),
    ],
)
def test_names_with_the_same_numbers_are_left_to_the_similarity(a, b):
    assert not numbers_differ(a, b)


def test_the_signature_ignores_order_and_leading_zeros():
    assert number_signature("rev 07 of 2026") == number_signature("2026, rev 7")


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("one hundred rows", "100 rows"),
        ("two thousand and five", "2005"),
        ("Phase one hundred twenty", "Phase 120"),
    ],
)
def test_number_words_it_cannot_read_are_left_to_the_similarity(a, b):
    assert number_signature(a) is None
    assert not numbers_differ(a, b)


def test_only_adjacent_words_form_one_number():
    assert number_signature("twenty, one") == number_signature("twenty")
    assert number_signature("twenty steps, first") == ("1", "20")
