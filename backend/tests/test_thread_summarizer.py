"""
Unit tests for thread narrative construction (Module 5 / FR-27).
"""

from app.nlp.thread_summarizer import ThreadMessage, ThreadNormalizer


def test_messages_are_ordered_chronologically():
    normalizer = ThreadNormalizer()
    narrative = normalizer.build_narrative(
        [
            ThreadMessage(body="This is the second message in the thread.", received_at="2026-01-02"),
            ThreadMessage(body="This is the first message in the thread.", received_at="2026-01-01"),
        ]
    )
    first_pos = narrative.find("first message")
    second_pos = narrative.find("second message")
    assert 0 <= first_pos < second_pos


def test_signature_is_stripped_per_message():
    normalizer = ThreadNormalizer()
    narrative = normalizer.build_narrative(
        [ThreadMessage(body="Please review the attached contract.\n--\nBest regards,\nBob Jones")]
    )
    assert "Bob Jones" not in narrative
    assert "review the attached contract" in narrative.lower()


def test_near_duplicate_quoted_content_is_not_repeated():
    """FR-27: 'Prevent the same content from being summarized repeatedly.'"""
    normalizer = ThreadNormalizer()
    original = (
        "We need to finalize the marketing budget allocation before the end of the week "
        "because finance is closing the books on Friday afternoon."
    )
    narrative = normalizer.build_narrative(
        [
            ThreadMessage(body=original, received_at="2026-01-01"),
            # Near-identical restatement (as an inline quote survives per-message
            # signature/quote stripping) -- should be dropped as a near-duplicate.
            ThreadMessage(body=original + " Agreed.", received_at="2026-01-02"),
        ]
    )
    # The shared sentence should appear only once in the final narrative,
    # not twice back-to-back.
    assert narrative.count("finalize the marketing budget allocation") == 1


def test_genuinely_different_messages_are_both_kept():
    normalizer = ThreadNormalizer()
    narrative = normalizer.build_narrative(
        [
            ThreadMessage(body="The budget review is scheduled for Thursday.", received_at="2026-01-01"),
            ThreadMessage(body="I also need the vendor invoice paid by Friday.", received_at="2026-01-02"),
        ]
    )
    assert "budget review" in narrative
    assert "vendor invoice" in narrative


def test_empty_messages_list_returns_empty_string():
    normalizer = ThreadNormalizer()
    assert normalizer.build_narrative([]) == ""
