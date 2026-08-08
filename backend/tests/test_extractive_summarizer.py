"""
Unit tests for ExtractiveSummarizer / TextRank (Module 5). Fast,
deterministic, no model download — this is pure TF-IDF + PageRank over
sklearn/networkx, the same class of dependency-light test spam/priority/
category's pipeline tests already are.
"""

from app.nlp.extractive_summarizer import ExtractiveSummarizer, split_sentences

LONG_TEXT = (
    "The quarterly report shows strong growth in the enterprise segment. "
    "Revenue increased by twelve percent compared to last year. "
    "The marketing team launched three new campaigns this quarter. "
    "Customer satisfaction scores remained stable throughout the period. "
    "The engineering team shipped four major features on schedule. "
    "Overall the company is well positioned heading into next quarter."
)


def test_split_sentences_drops_degenerate_fragments():
    sentences = split_sentences("Hi. This is a real sentence. Ok.")
    # "Hi." and "Ok." are single-token fragments and should be dropped;
    # only the real sentence should survive, WITH its trailing period
    # retained (see split_sentences' docstring for why that matters).
    assert sentences == ["This is a real sentence."]


def test_split_sentences_handles_empty_input():
    assert split_sentences("") == []
    assert split_sentences(None) == []  # type: ignore[arg-type]
    assert split_sentences("   ") == []


def test_short_text_is_returned_unchanged():
    summarizer = ExtractiveSummarizer()
    short = "This is one sentence. This is another one."
    result = summarizer.summarize(short, max_sentences=5)
    # Fewer sentences than max_sentences -- nothing to extract FROM.
    assert result == "This is one sentence. This is another one."


def test_summarize_returns_requested_sentence_count():
    summarizer = ExtractiveSummarizer()
    result = summarizer.summarize(LONG_TEXT, max_sentences=2)
    result_sentences = split_sentences(result)
    assert len(result_sentences) == 2


def test_summarize_preserves_original_document_order():
    """TextRank ranks by centrality, not position -- but the FINAL summary
    must still read in original document order, not rank order, or it
    reads as a jumbled sentence salad."""
    summarizer = ExtractiveSummarizer()
    result = summarizer.summarize(LONG_TEXT, max_sentences=3)

    original_sentences = split_sentences(LONG_TEXT)
    result_sentences = split_sentences(result)

    original_positions = [original_sentences.index(s) for s in result_sentences]
    assert original_positions == sorted(original_positions)


def test_summarize_is_deterministic():
    summarizer = ExtractiveSummarizer()
    first = summarizer.summarize(LONG_TEXT, max_sentences=2)
    second = summarizer.summarize(LONG_TEXT, max_sentences=2)
    assert first == second


def test_summarize_handles_empty_input_gracefully():
    summarizer = ExtractiveSummarizer()
    assert summarizer.summarize("", max_sentences=3) == ""


def test_summarize_handles_degenerate_near_identical_sentences():
    """A pathological case (every sentence near-identical) must not crash
    the PageRank/cosine-similarity machinery -- falls back to positional
    selection if convergence fails (see ExtractiveSummarizer.summarize)."""
    summarizer = ExtractiveSummarizer()
    repetitive = ". ".join(["This is the same sentence over and over"] * 10)
    result = summarizer.summarize(repetitive, max_sentences=3)
    assert isinstance(result, str)
    assert len(result) > 0
