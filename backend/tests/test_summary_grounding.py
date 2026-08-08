"""
Unit tests for entity-preservation grounding (Module 5 / FR-26). Loads a
real spaCy NER pipeline (en_core_web_sm, already a dependency via
EmailPreprocessor) — not mocked, since the whole point is verifying real
entity extraction, not a stub that always returns the right answer.
"""

from app.nlp.summary_grounding import check_preservation, extract_entities


def test_extract_entities_finds_dates_amounts_and_names():
    text = "John Smith needs the $4,200 invoice paid by Friday, August 14th."
    dates, amounts, names = extract_entities(text)

    assert "Friday" in dates or "August 14th" in dates
    assert "$4,200" in amounts
    assert "John Smith" in names


def test_extract_entities_finds_spelled_out_amounts():
    text = "The proposal exceeds budget by approximately 15000 dollars."
    _, amounts, _ = extract_entities(text)
    assert any("15000 dollars" in a.lower() for a in amounts)


def test_extract_entities_handles_empty_text():
    assert extract_entities("") == ([], [], [])
    assert extract_entities(None) == ([], [], [])  # type: ignore[arg-type]


def test_preservation_rate_is_none_when_source_has_no_entities():
    report = check_preservation(
        "Please let me know your thoughts on the proposal.", "Thoughts requested on proposal."
    )
    assert report.source_dates == []
    assert report.source_amounts == []
    assert report.source_names == []
    assert report.preservation_rate is None


def test_preservation_rate_is_one_when_everything_survives():
    source = "Pay John Smith $500 by Friday."
    summary = "Pay John Smith $500 by Friday."  # extractive-style: verbatim
    report = check_preservation(source, summary)
    assert report.preservation_rate == 1.0


def test_preservation_rate_reflects_partial_preservation():
    source = "John Smith needs $500 paid by Friday, and Sarah Lee needs $300 by Monday."
    summary = "John Smith needs $500 paid by Friday."  # drops Sarah Lee / $300 / Monday
    report = check_preservation(source, summary)
    assert 0.0 < report.preservation_rate < 1.0
    assert "John Smith" in report.preserved_names
    assert "Sarah Lee" not in report.preserved_names


def test_preservation_matching_is_case_insensitive():
    source = "Contact John Smith about the $200 refund."
    summary = "contact john smith about the $200 refund."
    report = check_preservation(source, summary)
    assert report.preservation_rate == 1.0
