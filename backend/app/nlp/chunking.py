"""
Long-email handling for the abstractive path (Step 13 — what happens when
an email/thread exceeds the model's context window).

Why map-reduce (chunk -> summarize each -> summarize the summaries), not
truncation: truncation silently drops whatever comes after the cutoff —
for an email, that could be the actual action item or deadline, i.e.
exactly what FR-26 requires preserving. A model card that says "long
emails are truncated" would be disclosing data loss, not preventing it.
Map-reduce costs more inference calls but keeps the whole document in the
process. Extractive summarization does NOT need this (TextRank considers
every sentence in the document regardless of length — no model context
window applies to it at all), so this module is abstractive-path-only.

Why word-count chunking, not exact tokenization: exact BPE token counts
require the tokenizer, which means importing transformers just to decide
chunk boundaries — a real cost for a decision that only needs to be
approximately right (the chunk target below is set with enough margin that
BPE's typical ~1.3x word-to-token expansion still lands under the model's
1024-token limit; the abstractive summarizer's own tokenizer call still
truncates defensively as a backstop if this estimate is ever wrong for
unusually token-dense text).
"""

from dataclasses import dataclass

from app.nlp.abstractive_summarizer import AbstractiveResult, AbstractiveSummarizer
from app.nlp.extractive_summarizer import split_sentences

# ~700 words * ~1.3 tokens/word (typical English BPE expansion) ~= 910
# tokens, comfortably under MODEL_MAX_INPUT_TOKENS (1024) even before the
# tokenizer's own truncation backstop.
WORDS_PER_CHUNK = 700


@dataclass
class ChunkedSummaryResult:
    summary: str
    num_chunks: int
    chunk_summaries: list[str]


def split_into_chunks(text: str, words_per_chunk: int = WORDS_PER_CHUNK) -> list[str]:
    """
    Chunks on sentence boundaries (never mid-sentence — cutting a sentence
    in half mid-chunk would hand the model a syntactically broken input for
    two separate generations instead of one coherent one).
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_word_count = 0

    for sentence in sentences:
        sentence_word_count = len(sentence.split())
        if current_chunk and current_word_count + sentence_word_count > words_per_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_word_count = 0
        current_chunk.append(sentence)
        current_word_count += sentence_word_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def summarize_long_text(
    text: str, summarizer: AbstractiveSummarizer, max_length: int = 60, min_length: int = 15
) -> ChunkedSummaryResult:
    """
    Map-reduce: summarize each chunk independently (map), then summarize
    the concatenation of chunk-summaries as the final reduce pass. If the
    text fits in one chunk, this degrades to a single ordinary call —
    callers don't need to branch on document length themselves.
    """
    chunks = split_into_chunks(text)

    if len(chunks) <= 1:
        result: AbstractiveResult = summarizer.summarize(text, max_length=max_length, min_length=min_length)
        return ChunkedSummaryResult(summary=result.summary, num_chunks=1, chunk_summaries=[result.summary])

    chunk_summaries = [
        summarizer.summarize(chunk, max_length=max_length, min_length=min_length).summary
        for chunk in chunks
    ]

    reduce_input = " ".join(chunk_summaries)
    final = summarizer.summarize(reduce_input, max_length=max_length, min_length=min_length)

    return ChunkedSummaryResult(
        summary=final.summary, num_chunks=len(chunks), chunk_summaries=chunk_summaries
    )
