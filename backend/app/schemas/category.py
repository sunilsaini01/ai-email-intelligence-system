"""
API response contracts for email categorization (Module 4 / Phase 5).

Same optional-fields-with-documented-defaults pattern as
app/schemas/priority.py — reused verbatim rather than re-litigated, since
CategoryMLPipeline consumes the identical record shape (TF-IDF text +
ContentFeatures + MetadataFeatures) as PriorityMLPipeline. See
docs/data_audit_categorization.md §5 for exactly which signals are real vs.
included-for-pipeline-consistency-only (notably: time-of-day/day-of-week are
real features but not expected to carry strong category signal, unlike
priority where FR-17 names them directly).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CategoryPredictionRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body (HTML or plain text).")
    sender_email: str = Field(default="", description="Used for domain-based metadata features only.")
    received_at: datetime | None = Field(
        default=None, description="Defaults to now() if omitted."
    )
    recipient_to: list[str] = Field(default_factory=list)
    recipient_cc: list[str] = Field(default_factory=list)
    is_reply: bool | None = Field(
        default=None, description="Auto-derived from subject's 'Re:' prefix if omitted."
    )
    is_forward: bool | None = Field(
        default=None, description="Auto-derived from subject's 'Fwd:'/'Fw:' prefix if omitted."
    )
    has_attachments: bool = Field(default=False)
    attachment_count: int = Field(default=0)


class CategoryScore(BaseModel):
    category: str
    confidence: float


class CategoryPredictionResponse(BaseModel):
    categories: list[CategoryScore]  # only categories that crossed the decision threshold (FR-24)
    all_scores: dict[str, float]  # full distribution over all 8 taxonomy labels
    model_version: str
    processing_ms: float


class CategoryFeedbackRequest(BaseModel):
    subject: str = Field(default="")
    body: str
    predicted_categories: list[str]
    corrected_categories: list[str]
    comment: str | None = None
    reviewer_id: str | None = Field(default=None, description="Caller-supplied, unauthenticated (Phase 11 FR-59).")


class CategoryFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
