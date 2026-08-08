"""
Extractive summarization — TextRank over TF-IDF sentence similarity
(PRD Sec9.1's named baseline architecture; FR-28's "key sentence selection"
half of the extractive/abstractive requirement).

Why TextRank, not "first-N sentences": first-N is a valid, even simpler
baseline (PRD Step 7 explicitly allows it), but for email specifically the
most important sentence is frequently NOT the first one — a "please submit
the invoice by Friday" action item buried mid-email would be silently
dropped by a first-N strategy. TextRank scores every sentence by how
central it is to the document's overall content (via PageRank over a
sentence-similarity graph), which is a real, if modest, improvement over
position alone and costs nothing extra at inference time TF-IDF wasn't
already going to compute anyway.

Why this belongs in app/nlp/, not app/pipeline/ or app/feature_engineering/:
this is a text-GENERATION task (selecting and returning source sentences),
not a classification pipeline that trains a persisted estimator — it has
no fit/predict/classes_ shape to share with MLPipeline/PriorityMLPipeline/
CategoryMLPipeline, and forcing it into that shape would be a worse fit
than a new, small, honestly-different module.
"""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    import networkx as nx
except ImportError as e:  # pragma: no cover - environment guard, not a runtime branch
    raise ImportError(
        "networkx is required for extractive summarization (TextRank). "
        "Add it to requirements.txt if this error surfaces in a fresh environment."
    ) from e

import re

# Same sentence-boundary characters as SENTENCE_PATTERN
# (app/feature_engineering/patterns.py), but capturing each sentence WITH
# its trailing punctuation instead of discarding it. Using
# `SENTENCE_PATTERN.split()` directly (as content_features.py does, for
# counting) is fine when only a count is needed -- it is NOT fine here,
# where the extracted sentences get rejoined into a summary: discarding
# the terminal punctuation meant a 3-sentence summary came back as one
# run-on string with no periods between the original sentences at all
# (caught by this phase's own tests, not shipped silently).
_SENTENCE_WITH_PUNCTUATION = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")


def split_sentences(text: str) -> list[str]:
    """Splits into sentences, each RETAINING its own trailing punctuation
    (".", "!", "?", or runs like "?!") — see module note above for why
    that matters for anything that re-joins the output, not just counts it."""
    if not text or not text.strip():
        return []
    raw_sentences = [s.strip() for s in _SENTENCE_WITH_PUNCTUATION.findall(text) if s.strip()]
    # Drop degenerate single-token "sentences" (stray punctuation artifacts,
    # e.g. from "Mr. Smith" splitting on the abbreviation's period) — a
    # length-1 fragment can never be a meaningful extractive summary
    # sentence and only adds graph noise.
    return [s for s in raw_sentences if len(s.split()) > 2]


class ExtractiveSummarizer:
    """
    TextRank: TF-IDF-vectorize each sentence, build a cosine-similarity
    graph between sentences, rank by PageRank centrality, return the
    top-K highest-ranked sentences IN THEIR ORIGINAL DOCUMENT ORDER (not
    rank order — a summary reads as a jumbled sentence salad otherwise).
    """

    def summarize(self, text: str, max_sentences: int = 3) -> str:
        """
        `max_sentences=3` matches FR-25's "2-3 sentence summary" upper
        bound by default — callers needing a different length (e.g. a
        longer thread summary, FR-27) pass a different value explicitly
        rather than this defaulting silently to the wrong shape elsewhere.
        """
        sentences = split_sentences(text)

        if len(sentences) <= max_sentences:
            # Nothing to extract FROM beyond what's already short enough —
            # returning the whole (short) text is more honest than forcing
            # a "summary" that's the same length as the input.
            return " ".join(sentences)

        try:
            vectorizer = TfidfVectorizer(stop_words="english")
            tfidf_matrix = vectorizer.fit_transform(sentences)
        except ValueError:
            # All sentences were pure stopwords/empty after vectorization
            # (rare, but possible on very short or degenerate input) — fall
            # back to positional selection rather than crashing.
            return " ".join(sentences[:max_sentences])

        similarity_matrix = cosine_similarity(tfidf_matrix)
        # Zero the diagonal -- a sentence's similarity to itself must not
        # contribute to its own centrality score.
        np.fill_diagonal(similarity_matrix, 0)

        graph = nx.from_numpy_array(similarity_matrix)
        try:
            scores = nx.pagerank(graph)
        except nx.PowerIterationFailedConvergence:
            # Degenerate graphs (e.g. near-identical sentences) can fail to
            # converge -- fall back to positional selection rather than
            # raising out of what's supposed to be a robust baseline.
            return " ".join(sentences[:max_sentences])

        ranked_indices = sorted(scores, key=scores.get, reverse=True)[:max_sentences]
        selected_in_order = sorted(ranked_indices)  # restore original document order

        return " ".join(sentences[i] for i in selected_in_order)
