"""Unit tests for the Levenshtein edit-distance helper (Post-Phase-10 fix #2)."""

from app.nlp.edit_distance import compute_edit_distance


def test_identical_strings_have_zero_distance():
    assert compute_edit_distance("hello world", "hello world") == 0


def test_empty_strings_have_zero_distance():
    assert compute_edit_distance("", "") == 0


def test_one_empty_string_equals_length_of_other():
    assert compute_edit_distance("", "hello") == 5
    assert compute_edit_distance("hello", "") == 5


def test_single_character_substitution():
    assert compute_edit_distance("cat", "bat") == 1


def test_single_character_insertion():
    assert compute_edit_distance("cat", "cats") == 1


def test_single_character_deletion():
    assert compute_edit_distance("cats", "cat") == 1


def test_none_treated_as_empty_string():
    assert compute_edit_distance(None, "hello") == 5
    assert compute_edit_distance("hello", None) == 5


def test_completely_different_strings():
    assert compute_edit_distance("abc", "xyz") == 3
