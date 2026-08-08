"""
API response contracts for email summarization (Module 5 / Phase 6).

Why `summary_type` defaults to "extractive," not "abstractive": measured
directly this phase (docs/model_cards/email_summarization.md
"Performance") — the abstractive path's ~9.2s average latency blows the
PRD's own SLA (P50 < 2s, P95 < 4s, hard limit 8s, PRD Sec6.1) by a wide
margin on this CPU-only environment, while extractive's ~3ms average is
trivially within it. FR-28 requires BOTH be *supported* (available), not
that either be the default — defaulting to the one that actually meets the
PRD's own non-functional requirement is the defensible choice, not an
arbitrary one.

Why `messages` (plural, optional) alongside `body` (singular): FR-27
requires whole-thread summarization as one cohesive narrative. A single
`body` field can't express "these N messages are one thread" — see
app/nlp/thread_summarizer.py for how `messages` gets turned into one
narrative before summarization.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ThreadMessageInput(BaseModel):
    body: str
    received_at: str | None = None  # ISO string; ordering key for thread narrative construction


class SummarizationRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str | None = Field(
        default=None, description="Single email body. Mutually exclusive with `messages`."
    )
    messages: list[ThreadMessageInput] | None = Field(
        default=None,
        description="Thread messages (FR-27) — mutually exclusive with `body`. "
        "Summarized as one cohesive narrative, not per-message.",
    )
    summary_type: Literal["extractive", "abstractive"] = Field(
        default="extractive",
        description="extractive (TextRank, fast, meets the PRD latency SLA) or "
        "abstractive (distilbart-cnn-6-6, slower — see the model card's measured latency "
        "before using this in a latency-sensitive path).",
    )
    max_sentences: int = Field(
        default=3, ge=1, le=10, description="Extractive-only. FR-25 targets 2-3."
    )

    @model_validator(mode="after")
    def _exactly_one_input_source(self) -> "SummarizationRequest":
        has_body = bool(self.body and self.body.strip())
        has_messages = bool(self.messages)
        if has_body == has_messages:  # both or neither
            raise ValueError("Provide exactly one of `body` or `messages`, not both/neither.")
        return self


class PreservedEntities(BaseModel):
    dates: list[str]
    monetary_amounts: list[str]
    names: list[str]


class SummarizationResponse(BaseModel):
    summary: str
    summary_type: Literal["extractive", "abstractive"]
    skipped_short_input: bool = Field(
        description="True if the input was <=200 words (FR-25) and returned as-is "
        "instead of being forced through a summarizer."
    )
    input_word_count: int
    preserved_entities: PreservedEntities
    entity_preservation_rate: float | None = Field(
        description="Fraction of source dates/amounts/names found in the summary "
        "(FR-26). None if the source contained no such entities at all — see "
        "app/nlp/summary_grounding.py for why that's not the same as 0.0."
    )
    model_version: str
    processing_ms: float


class SummarizationFeedbackRequest(BaseModel):
    original_text: str
    generated_summary: str
    accepted: bool
    corrected_summary: str | None = None
    quality_score: int | None = Field(default=None, ge=1, le=5)
    reason: str | None = None


class SummarizationFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
