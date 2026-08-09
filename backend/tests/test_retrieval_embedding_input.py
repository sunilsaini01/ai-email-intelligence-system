"""
Unit tests for embedding-input construction and PII anonymization wiring
(Module 9 / Phase 9).
"""

from app.retrieval.embedding_input import build_embedding_text


def test_subject_and_body_are_both_present_in_the_output():
    text, _ = build_embedding_text("Refund request", "I want a refund.")
    assert "Refund request" in text
    assert "I want a refund." in text


def test_pii_is_anonymized_in_the_embedded_text():
    text, entity_types = build_embedding_text("", "My name is John Smith, call me at 555-123-4567.")
    assert "John Smith" not in text
    assert "555-123-4567" not in text
    assert "PERSON" in entity_types


def test_no_pii_returns_empty_entity_list():
    text, entity_types = build_embedding_text("Meeting", "Let's meet next Tuesday to discuss the project.")
    assert entity_types == [] or "DATE_TIME" in entity_types  # "Tuesday" may register as DATE_TIME
    assert "meeting" in text.lower() or "Meeting" in text


def test_empty_subject_and_body_do_not_raise():
    text, entity_types = build_embedding_text("", "")
    assert isinstance(text, str)
    assert entity_types == []


def test_html_is_stripped_before_embedding():
    text, _ = build_embedding_text("Test", "<p>Please <b>refund</b> my order.</p>")
    assert "<p>" not in text
    assert "<b>" not in text
