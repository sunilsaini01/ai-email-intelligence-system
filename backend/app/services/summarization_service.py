"""
Email summarization service (Module 5).

Orchestrates: preprocessing (single email or thread) -> short-input
passthrough (FR-25) -> extractive or abstractive summarization -> entity
grounding (FR-26) -> response. Mirrors SpamService/PriorityService/
CategoryService's role (the API layer only deals with request/response
schemas; this is where the actual domain logic lives) despite the task
itself being generation, not classification.

Why the abstractive model is lazy-loaded, not warmed at startup like
spam/priority/category: those three take ~9s combined to warm (measured,
docs/architecture_priority_classification.md). The abstractive summarizer
alone takes ~115s on first load (docs/model_cards/email_summarization.md
"Performance") — eagerly warming it would make every fresh process take
nearly two minutes to become ready, a straightforwardly bad startup-latency
trade for a path most requests won't even use (extractive is the default
— see app/schemas/summarization.py). The extractive path (TextRank) has no
comparable load cost and IS warmed at startup, same pattern as the other
three modules for the parts of this module that are actually cheap to warm.
"""

import time
from functools import lru_cache

from app.nlp.chunking import summarize_long_text
from app.nlp.extractive_summarizer import ExtractiveSummarizer
from app.nlp.summary_grounding import check_preservation
from app.nlp.thread_summarizer import ThreadMessage, ThreadNormalizer
from app.preprocessing.email_preprocessor import SUMMARY_CONFIG, EmailPreprocessor

# FR-25: "generate a 2-3 sentence summary for emails longer than 200 words"
# -- read as a floor, not just a length preference: forcing something
# already at or under this length through a summarizer risks the model
# inventing content to fill space, which is a worse outcome than returning
# the (already short) source text unchanged.
SHORT_INPUT_WORD_THRESHOLD = 200


class SummarizationService:
    def __init__(self):
        self.preprocessor = EmailPreprocessor(SUMMARY_CONFIG)
        self.extractive_summarizer = ExtractiveSummarizer()
        self.thread_normalizer = ThreadNormalizer()

    def _build_source_text(
        self, body: str | None, messages: list[dict] | None
    ) -> str:
        if messages:
            thread_messages = [
                ThreadMessage(body=m["body"], received_at=m.get("received_at")) for m in messages
            ]
            return self.thread_normalizer.build_narrative(thread_messages)
        return self.preprocessor.process(body or "")

    def summarize(
        self,
        subject: str = "",
        body: str | None = None,
        messages: list[dict] | None = None,
        summary_type: str = "extractive",
        max_sentences: int = 3,
    ) -> dict:
        start = time.perf_counter()

        source_text = self._build_source_text(body, messages)
        # Subject isn't summarized separately -- it's short by construction
        # and FR-25/26/27 are about body/thread content, but it's prepended
        # so a subject-only signal (e.g. "URGENT: contract expires Friday")
        # isn't invisible to extractive TextRank's sentence-graph, matching
        # how ContentFeatureExtractor treats subject+body together elsewhere
        # in this codebase.
        full_text = f"{subject.strip()} {source_text}".strip() if subject else source_text

        word_count = len(full_text.split())
        skipped_short_input = word_count <= SHORT_INPUT_WORD_THRESHOLD

        if skipped_short_input:
            summary = full_text
            model_version = "none (short-input passthrough, FR-25)"
        elif summary_type == "extractive":
            summary = self.extractive_summarizer.summarize(full_text, max_sentences=max_sentences)
            model_version = "textrank-tfidf-v1"
        else:
            from app.nlp.abstractive_summarizer import MODEL_NAME, get_abstractive_summarizer

            abstractive = get_abstractive_summarizer()
            chunked = summarize_long_text(full_text, abstractive)
            summary = chunked.summary
            model_version = MODEL_NAME

        report = check_preservation(full_text, summary)
        processing_ms = round((time.perf_counter() - start) * 1000, 2)

        return {
            "summary": summary,
            "summary_type": summary_type,
            "skipped_short_input": skipped_short_input,
            "input_word_count": word_count,
            "preserved_entities": {
                "dates": report.preserved_dates,
                "monetary_amounts": report.preserved_amounts,
                "names": report.preserved_names,
            },
            "entity_preservation_rate": report.preservation_rate,
            "model_version": model_version,
            "processing_ms": processing_ms,
        }


@lru_cache
def get_summarization_service() -> SummarizationService:
    return SummarizationService()
