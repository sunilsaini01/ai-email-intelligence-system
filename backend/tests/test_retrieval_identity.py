"""
Unit tests for content-hash identity (Module 9 / Phase 9).
"""

from app.retrieval.identity import compute_content_hash


def test_same_content_produces_same_hash():
    h1 = compute_content_hash("Refund", "I want a refund.")
    h2 = compute_content_hash("Refund", "I want a refund.")
    assert h1 == h2


def test_different_content_produces_different_hash():
    h1 = compute_content_hash("Refund", "I want a refund.")
    h2 = compute_content_hash("Refund", "I want a different thing.")
    assert h1 != h2


def test_whitespace_differences_do_not_change_identity():
    h1 = compute_content_hash("Refund", "I want   a refund.")
    h2 = compute_content_hash("Refund", "I want a refund.")
    assert h1 == h2


def test_case_differences_do_not_change_identity():
    h1 = compute_content_hash("REFUND", "I WANT A REFUND.")
    h2 = compute_content_hash("refund", "i want a refund.")
    assert h1 == h2


def test_subject_and_body_are_both_part_of_identity():
    h1 = compute_content_hash("Subject A", "Same body")
    h2 = compute_content_hash("Subject B", "Same body")
    assert h1 != h2


def test_hash_is_a_fixed_length_hex_string():
    h = compute_content_hash("x", "y")
    assert len(h) == 64
    int(h, 16)  # raises ValueError if not valid hex


def test_empty_subject_and_body_do_not_raise():
    h = compute_content_hash("", "")
    assert isinstance(h, str) and len(h) == 64
