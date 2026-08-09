"""
Unit tests for the routing keyword engine (Module 8 / Phase 8).

Specifically covers word-boundary safety -- the property the codebase's
existing keyword check (content_features.py's plain substring containment)
does NOT have, and the reason this module exists as separate, new code
rather than reusing that one. See app/routing/keyword_matcher.py's module
docstring.
"""

from app.routing.keyword_matcher import (
    MAX_MATCH_INPUT_CHARS,
    match_department_keywords,
    top_department_by_keywords,
)


def test_word_boundary_prevents_substring_false_positive():
    # "help" is a Support keyword; "helper" must NOT match it -- content_features.py's
    # plain substring check WOULD match "helper" here, which is the exact class of bug
    # this module fixes for routing.
    votes = match_department_keywords("Please assign me a helper for this task.")
    assert votes.get("Support", 0) == 0


def test_exact_word_boundary_match_is_counted():
    votes = match_department_keywords("I need help with a bug in the app.")
    assert votes.get("Support", 0) >= 1


def test_case_insensitive_matching():
    votes = match_department_keywords("Please review the INVOICE for last month.")
    assert votes.get("Billing", 0) == 1


def test_counts_multiple_occurrences_of_the_same_keyword():
    votes = match_department_keywords("invoice invoice invoice")
    assert votes["Billing"] == 3


def test_multiword_phrase_matches_across_irregular_whitespace():
    votes = match_department_keywords("It has stopped   working\tsince yesterday.")
    assert votes.get("Support", 0) >= 1  # "stopped working" phrase, collapsed whitespace


def test_no_match_returns_empty_dict_not_zeros():
    votes = match_department_keywords("The weather today is pleasant and sunny.")
    assert votes == {}


def test_top_department_returns_none_when_no_evidence():
    winner, votes = top_department_by_keywords("nothing relevant here at all")
    assert winner is None
    assert votes == {}


def test_top_department_tie_break_is_deterministic_and_alphabetical():
    # One Sales keyword ("quote"), one Support keyword ("help") -- a 1-1 tie.
    winner, votes = top_department_by_keywords("Can you send a quote, and also help me?")
    assert votes == {"Sales": 1, "Support": 1}
    assert winner == "Sales"  # alphabetically first among the tied departments


def test_input_beyond_max_length_is_truncated_not_rejected():
    huge_body = "invoice " * 10_000  # far beyond MAX_MATCH_INPUT_CHARS
    votes = match_department_keywords(huge_body)
    assert votes["Billing"] > 0
    # A crude upper bound: can't exceed roughly one match per ~8 chars of the capped input.
    assert votes["Billing"] <= (MAX_MATCH_INPUT_CHARS // len("invoice ")) + 1


def test_empty_and_none_input_do_not_raise():
    assert match_department_keywords("") == {}
    assert match_department_keywords(None) == {}
