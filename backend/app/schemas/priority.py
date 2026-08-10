"""
API response contracts for priority classification (Module 3 / Phase 4).

Why most fields beyond subject/body are optional with defaults: FR-17 names
sender history, subject keywords, body sentiment, and time of day as inputs,
but a caller often won't have all of them at request time. Every optional
field here has a documented, identical default used both here and in
training (see app/pipeline/priority_pipeline.py's `_record_to_features`) —
see docs/data_audit_priority.md §5 for exactly which signals are real vs.
defaulted, and why sender history isn't a field at all (no data source for
it exists in this codebase yet).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class PriorityPredictionRequest(BaseModel):
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


class PriorityPredictionResponse(BaseModel):
    priority: str  # "Critical" | "High" | "Medium" | "Low"
    confidence: float  # probability assigned to the predicted label
    probabilities: dict[str, float]  # full distribution over all 4 classes
    model_version: str
    processing_ms: float


class PriorityFeedbackRequest(BaseModel):
    subject: str = Field(default="")
    body: str
    predicted_label: str
    corrected_label: str
    comment: str | None = None
    reviewer_id: str | None = Field(default=None, description="Caller-supplied, unauthenticated (Phase 11 FR-59).")


class PriorityFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
