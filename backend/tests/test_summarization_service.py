"""
Unit tests for SummarizationService (Module 5). The abstractive path is
exercised via a monkeypatched get_abstractive_summarizer (no 300MB model
download/inference in the regular suite — see
tests/test_abstractive_summarizer_slow.py for the real, opt-in integration
test) so these tests stay fast and network-independent, matching this
project's existing "fast unit tests + separate slow/opt-in integration
test" split (e.g. spam/priority/category's endpoint tests skip on missing
artifact rather than requiring one in every run).
"""

import pytest

from app.services.summarization_service import SHORT_INPUT_WORD_THRESHOLD, SummarizationService


@pytest.fixture
def service():
    return SummarizationService()


def _long_body(word_count: int = 250) -> str:
    return ". ".join(f"This is filler sentence number {i} in a long email" for i in range(word_count // 8)) + "."


def test_short_input_is_passed_through_unsummarized(service):
    """FR-25: only emails longer than 200 words get summarized."""
    short = "Quick question — are we still on for lunch tomorrow?"
    result = service.summarize(body=short)

    assert result["skipped_short_input"] is True
    assert result["model_version"].startswith("none")
    assert result["input_word_count"] <= SHORT_INPUT_WORD_THRESHOLD


def test_long_input_is_summarized(service):
    result = service.summarize(body=_long_body(300), summary_type="extractive")

    assert result["skipped_short_input"] is False
    assert result["model_version"] == "textrank-tfidf-v1"
    assert len(result["summary"]) < len(_long_body(300))


def test_default_summary_type_is_extractive(service):
    """Set deliberately — see app/schemas/summarization.py's docstring for
    why (the abstractive path blows the PRD's own latency SLA on this
    environment, measured in the model card)."""
    result = service.summarize(body=_long_body(300))
    assert result["summary_type"] == "extractive"


def test_thread_messages_are_combined_into_one_narrative(service):
    messages = [
        {"body": _long_body(150), "received_at": "2026-01-01"},
        {"body": "A short follow-up reply.", "received_at": "2026-01-02"},
    ]
    result = service.summarize(messages=messages, summary_type="extractive")
    assert result["input_word_count"] > 150  # both messages contributed


def test_response_includes_entity_preservation_fields(service):
    body = _long_body(300) + " Please pay John Smith $500 by Friday for the invoice."
    result = service.summarize(body=body, summary_type="extractive")

    assert "preserved_entities" in result
    assert set(result["preserved_entities"].keys()) == {"dates", "monetary_amounts", "names"}
    assert result["entity_preservation_rate"] is None or 0.0 <= result["entity_preservation_rate"] <= 1.0


def test_abstractive_path_routes_to_abstractive_summarizer(service, monkeypatch):
    """Verifies the SERVICE correctly routes to the abstractive path and
    shapes its output the same way — using a fake summarizer so this test
    doesn't need the real ~300MB model."""

    class _FakeAbstractive:
        def summarize(self, text, max_length=60, min_length=15):
            from app.nlp.abstractive_summarizer import AbstractiveResult

            return AbstractiveResult(
                summary="a fake abstractive summary",
                model_name="fake-model-for-testing",
                input_token_count=10,
                was_truncated=False,
                processing_ms=1.0,
            )

    import app.nlp.abstractive_summarizer as abstractive_module

    monkeypatch.setattr(
        abstractive_module, "get_abstractive_summarizer", lambda: _FakeAbstractive()
    )

    result = service.summarize(body=_long_body(300), summary_type="abstractive")

    assert result["summary_type"] == "abstractive"
    assert result["summary"] == "a fake abstractive summary"
    # model_version reports the module's configured MODEL_NAME constant
    # (what's actually deployed), not something read off the injected fake
    # — the fake stands in for the model's BEHAVIOR (what summarize()
    # returns), not for which model is considered "the configured one."
    from app.nlp.abstractive_summarizer import MODEL_NAME

    assert result["model_version"] == MODEL_NAME
