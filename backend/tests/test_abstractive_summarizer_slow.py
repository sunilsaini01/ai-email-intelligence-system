"""
Real, end-to-end integration test for AbstractiveSummarizer — actually
downloads/loads sshleifer/distilbart-cnn-6-6 (~115s cold, per the model
card's measured numbers) and runs real inference. Skipped by default; every
other Phase 6 test exercises this path through a fake/mocked summarizer
(tests/test_summarization_service.py, tests/test_chunking.py) so the
regular suite stays fast and doesn't require network access or a ~115s
model download on every run.

Run explicitly with:
    RUN_SLOW_TESTS=1 PYTHONPATH=. python -m pytest tests/test_abstractive_summarizer_slow.py -v
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SLOW_TESTS") != "1",
    reason="Downloads/loads a real ~300MB model — opt in with RUN_SLOW_TESTS=1",
)


def test_real_model_produces_a_nonempty_summary():
    from app.nlp.abstractive_summarizer import MODEL_MAX_INPUT_TOKENS, AbstractiveSummarizer

    summarizer = AbstractiveSummarizer()
    text = (
        "Hi team, following up on our discussion yesterday about the Q3 budget review. "
        "We need to finalize the marketing spend allocation by Friday, August 14th. "
        "The current proposal exceeds budget by approximately 15000 dollars, so we need "
        "to trim expenses in the digital advertising category."
    )

    result = summarizer.summarize(text, max_length=60, min_length=15)

    assert len(result.summary) > 0
    assert result.model_name == "sshleifer/distilbart-cnn-6-6"
    assert result.input_token_count <= MODEL_MAX_INPUT_TOKENS
    assert result.was_truncated is False
    assert result.processing_ms > 0
