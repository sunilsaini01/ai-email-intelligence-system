"""
Unit tests for FR-35's entity extraction (Module 7).
"""

from app.nlp.intent_entities import (
    extract_intent_entities,
    extract_order_ids,
    extract_product_names,
)


def test_extract_order_ids_matches_the_prd_worked_example():
    assert extract_order_ids("Can you tell me the status of order #45821?") == ["45821"]


def test_extract_order_ids_handles_variant_phrasing():
    assert extract_order_ids("order number 12345") == ["12345"]
    assert extract_order_ids("order no. AB-9910") == ["AB-9910"]


def test_extract_order_ids_returns_empty_for_no_match():
    assert extract_order_ids("please schedule a call") == []


def test_extract_order_ids_handles_empty_text():
    assert extract_order_ids("") == []


def test_extract_intent_entities_combines_all_five_types():
    text = "Please refund order #45821 for John Smith, charged $120 on August 14th, 2026."
    entities = extract_intent_entities(text)

    assert entities.order_ids == ["45821"]
    assert "$120" in entities.monetary_amounts
    assert any("August" in d for d in entities.dates)
    assert "John Smith" in entities.person_names
    assert isinstance(entities.product_names, list)  # best-effort, may be empty


def test_extract_intent_entities_handles_empty_text():
    entities = extract_intent_entities("")
    assert entities.order_ids == []
    assert entities.dates == []
    assert entities.monetary_amounts == []
    assert entities.person_names == []
    assert entities.product_names == []


def test_extract_product_names_returns_a_list_without_raising():
    # Disclosed low-recall (see module docstring) -- this test asserts the
    # function doesn't crash and returns the right type, not that it
    # achieves any particular recall.
    result = extract_product_names("I ordered the Acme SuperWidget 3000 last week.")
    assert isinstance(result, list)
