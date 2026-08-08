"""
Thread-aware context construction (FR-27 — "System shall summarize an
entire email thread as a cohesive narrative, not per-message").

What FR-27 rules out: summarizing each message independently and
concatenating the N summaries. That produces N disjoint mini-summaries, not
one narrative, and (per FR-27's own follow-on requirement) risks
re-summarizing the same quoted content once per reply.

Approach: order messages chronologically, clean each one with
EmailPreprocessor(SUMMARY_CONFIG) — which already strips quoted-reply
blocks and signatures per-message (see email_preprocessor.py) — then
additionally drop any message whose cleaned body is near-identical to
content already included (the "same content summarized repeatedly" case
FR-27 names explicitly, for whatever quoted content survives per-message
stripping, e.g. an inline "> as I said before, ..." quote that isn't a
clean trailing block), and concatenate what's left into ONE text passed to
a summarizer as a single unit.
"""

from dataclasses import dataclass

from app.preprocessing.email_preprocessor import SUMMARY_CONFIG, EmailPreprocessor

_NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.8


@dataclass
class ThreadMessage:
    body: str
    received_at: str | None = None  # ISO string or None; sorting is stable if all None


def _jaccard_similarity(a: str, b: str) -> float:
    tokens_a, tokens_b = set(a.lower().split()), set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


class ThreadNormalizer:
    def __init__(self):
        self.preprocessor = EmailPreprocessor(SUMMARY_CONFIG)

    def build_narrative(self, messages: list[ThreadMessage]) -> str:
        """
        Returns one concatenated, deduplicated, chronologically-ordered
        text ready to hand to ExtractiveSummarizer/AbstractiveSummarizer —
        the "context construction" step, not summarization itself (kept
        separate so either summarizer can consume the same narrative
        without duplicating this logic per-summarizer-type).
        """
        ordered = sorted(messages, key=lambda m: m.received_at or "")

        cleaned_bodies: list[str] = []
        for message in ordered:
            cleaned = self.preprocessor.process(message.body)
            if not cleaned:
                continue

            is_near_duplicate = any(
                _jaccard_similarity(cleaned, prior) >= _NEAR_DUPLICATE_JACCARD_THRESHOLD
                for prior in cleaned_bodies
            )
            if is_near_duplicate:
                continue

            cleaned_bodies.append(cleaned)

        return " ".join(cleaned_bodies)
