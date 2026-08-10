"""
API response contracts for sentiment analysis (Module 6 / Phase 7A).

Simpler than priority's schema: no metadata fields (sender/received_at/...)
-- VaderSentimentPredictor is a pure text scorer, so there's nothing
analogous to consume. See docs/data_audit_sentiment.md for why `sentiment`
is one of the 5 FR-29 classes rather than a raw compound score, and why
`probabilities` is a disclosed heuristic distribution, not a calibrated one.
"""

from pydantic import BaseModel, Field


class SentimentPredictionRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body (HTML or plain text).")


class SentimentPredictionResponse(BaseModel):
    sentiment: str  # one of FR-29's 5 classes
    confidence: float
    probabilities: dict[str, float]  # heuristic distribution -- see model card "Calibration"
    model_version: str
    processing_ms: float


class SentimentFeedbackRequest(BaseModel):
    subject: str = Field(default="")
    body: str
    predicted_label: str
    corrected_label: str
    comment: str | None = None
    reviewer_id: str | None = Field(default=None, description="Caller-supplied, unauthenticated (Phase 11 FR-59).")


class SentimentFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
