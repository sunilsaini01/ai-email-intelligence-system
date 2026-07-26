"""
API response contracts for spam classification (Module 2 / Phase 3).
"""

from pydantic import BaseModel, Field


class SpamPredictionRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body (HTML or plain text).")


class SpamPredictionResponse(BaseModel):
    is_spam: bool
    status: str  # "quarantined" | "clear" — never "deleted" (FR-13)
    confidence: float  # probability assigned to the predicted label
    spam_score: float  # probability of the spam class specifically (FR-12)
    threshold_used: float
    model_version: str
    processing_ms: float


class SpamFeedbackRequest(BaseModel):
    subject: str = Field(default="")
    body: str
    predicted_label: str
    corrected_label: str
    comment: str | None = None


class SpamFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
