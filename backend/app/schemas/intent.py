"""
API response contracts for intent detection (Module 7 / Phase 7B).

`intents` is a list (may be empty, FR-33 has no default fallback class),
mirroring category.py's multi-label response shape. `entities` is FR-35's
extraction output, always present (independent of the classifier).
"""

from pydantic import BaseModel, Field


class IntentPredictionRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body (HTML or plain text).")


class IntentAssignment(BaseModel):
    intent: str
    confidence: float


class IntentEntitiesResponse(BaseModel):
    order_ids: list[str]
    dates: list[str]
    monetary_amounts: list[str]
    person_names: list[str]
    product_names: list[str]


class IntentPredictionResponse(BaseModel):
    intents: list[IntentAssignment]  # may be empty -- see module docstring
    all_scores: dict[str, float]
    entities: IntentEntitiesResponse
    model_version: str
    processing_ms: float


class IntentFeedbackRequest(BaseModel):
    subject: str = Field(default="")
    body: str
    predicted_label: list[str]
    corrected_label: list[str]
    comment: str | None = None


class IntentFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
