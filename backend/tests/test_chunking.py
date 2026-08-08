"""
Unit tests for long-email chunking (Module 5, Step 13). The map-reduce
summarize_long_text() itself needs a real/fake AbstractiveSummarizer;
split_into_chunks() (the part with actual logic worth testing) needs
neither model nor network, so it's tested directly and in isolation.
"""

from app.nlp.chunking import ChunkedSummaryResult, split_into_chunks, summarize_long_text


def test_short_text_produces_a_single_chunk():
    chunks = split_into_chunks("This is a short sentence. Another one here.", words_per_chunk=700)
    assert len(chunks) == 1


def test_long_text_is_split_into_multiple_chunks():
    long_text = ". ".join(f"This is sentence number {i} in a long document" for i in range(50)) + "."
    chunks = split_into_chunks(long_text, words_per_chunk=50)
    assert len(chunks) > 1


def test_chunks_never_exceed_the_word_budget_by_more_than_one_sentence():
    long_text = ". ".join(f"This is sentence number {i} in a long document" for i in range(50)) + "."
    words_per_chunk = 50
    chunks = split_into_chunks(long_text, words_per_chunk=words_per_chunk)
    for chunk in chunks[:-1]:  # last chunk may be a shorter remainder
        # Allow one sentence of slack (a chunk can exceed the budget by
        # at most one sentence's worth -- see split_into_chunks: it commits
        # a sentence to the current chunk before checking the NEXT one).
        assert len(chunk.split()) <= words_per_chunk + 15


def test_chunking_never_splits_mid_sentence():
    long_text = "First sentence here today. Second sentence follows now. Third and final sentence."
    chunks = split_into_chunks(long_text, words_per_chunk=5)
    for chunk in chunks:
        assert chunk.strip().endswith(".")


def test_empty_text_produces_no_chunks():
    assert split_into_chunks("") == []


class _FakeAbstractiveSummarizer:
    """Stands in for AbstractiveSummarizer -- no model download/inference
    needed to test the map-reduce ORCHESTRATION logic in
    summarize_long_text()."""

    def __init__(self):
        self.calls = []

    def summarize(self, text, max_length=60, min_length=15):
        from app.nlp.abstractive_summarizer import AbstractiveResult

        self.calls.append(text)
        return AbstractiveResult(
            summary=f"[summary of {len(text.split())} words]",
            model_name="fake-model",
            input_token_count=len(text.split()),
            was_truncated=False,
            processing_ms=1.0,
        )


def test_summarize_long_text_degrades_to_single_call_for_short_text():
    fake = _FakeAbstractiveSummarizer()
    result = summarize_long_text("A short piece of text.", fake)
    assert isinstance(result, ChunkedSummaryResult)
    assert result.num_chunks == 1
    assert len(fake.calls) == 1  # no reduce pass needed


def test_summarize_long_text_runs_map_then_reduce_for_long_text():
    fake = _FakeAbstractiveSummarizer()
    # summarize_long_text() uses chunking.py's default WORDS_PER_CHUNK (700)
    # with no override parameter -- needs a text well over that to actually
    # trigger multi-chunk behavior (200 sentences * ~8 words ~= 1600 words).
    long_text = ". ".join(f"This is sentence number {i} in a long document" for i in range(200)) + "."

    result = summarize_long_text(long_text, fake)

    assert result.num_chunks > 1
    # map calls (one per chunk) + exactly one reduce call over the
    # concatenated chunk summaries.
    assert len(fake.calls) == result.num_chunks + 1
    assert len(result.chunk_summaries) == result.num_chunks
