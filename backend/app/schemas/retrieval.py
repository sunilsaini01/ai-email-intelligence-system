"""
API contracts for similar-email retrieval (Module 9 / Phase 9, FR-43 to
FR-47).

`score` on `SimilarEmailMatch` is cosine similarity, NOT a probability
(RULE 5) -- roughly [-1, 1] in theory, practically closer to [0, 1] for
this project's non-negative-leaning text embeddings, higher means more
similar, and NOT comparable across different `embedding_model` values
(see docs/vector_store_decision.md "Similarity Metric"). Every response
that carries a score also carries `embedding_model` so a caller can tell
whether two scores came from the same model and are safe to compare.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.retrieval.resolution_status import DEFAULT_RESOLUTION_STATUS, RESOLUTION_STATUSES
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID


class RetrievalIndexRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body (HTML or plain text).")
    sender_email: str = Field(default="")
    received_at: datetime | None = Field(default=None, description="Defaults to now() if omitted.")
    category: str | None = Field(
        default=None, description="Caller-supplied snapshot -- e.g. from /categorization/predict. Not recomputed here."
    )
    department: str | None = Field(
        default=None, description="Caller-supplied snapshot -- e.g. from /routing/predict. Not recomputed here."
    )
    priority: str | None = Field(
        default=None,
        description="Caller-supplied snapshot -- e.g. from /priority/predict. Not recomputed here. "
        "Phase 11 addition, used by the dashboard's SLA calculation (docs/architecture_dashboard.md).",
    )
    organization_id: str = Field(default=DEFAULT_ORGANIZATION_ID)


class RetrievalIndexResponse(BaseModel):
    email_id: uuid.UUID
    content_hash: str
    was_created: bool = Field(description="False if this content was already indexed for this organization (idempotent re-index).")
    index_status: str
    embedding_model: str
    embedding_dimension: int
    pii_entity_types_found: list[str] = Field(
        description="PII entity TYPES detected in the embedded text (e.g. ['PERSON', 'EMAIL_ADDRESS']) -- never the raw values."
    )
    processing_ms: float


class SimilarEmailMatch(BaseModel):
    email_id: uuid.UUID
    score: float = Field(description="Cosine similarity, NOT a probability. See module docstring.")
    subject: str
    category: str | None
    department: str | None
    resolution_status: str
    received_at: datetime


class RetrievalSearchRequest(BaseModel):
    subject: str = Field(default="")
    body: str = Field(..., description="Query email's raw body -- does not need to already be indexed.")
    top_k: int = Field(default=5, ge=1, le=50, description="PRD's FR-44 default is 5.")
    category: str | None = Field(default=None, description="Filter (FR-46).")
    department: str | None = Field(default=None, description="Filter (FR-46).")
    resolution_status: str | None = Field(default=None, description="Filter (FR-46).")
    organization_id: str = Field(default=DEFAULT_ORGANIZATION_ID)


class RetrievalSearchResponse(BaseModel):
    query_id: uuid.UUID
    results: list[SimilarEmailMatch]
    embedding_model: str
    result_count: int
    processing_ms: float


class ResolutionStatusUpdateRequest(BaseModel):
    resolution_status: str = Field(description=f"One of {RESOLUTION_STATUSES}.")


class ResolutionStatusUpdateResponse(BaseModel):
    email_id: uuid.UUID
    resolution_status: str


class RetrievalFeedbackRequest(BaseModel):
    query_subject: str = Field(default="")
    query_body: str
    result_email_id: uuid.UUID | None = Field(default=None, description="Which returned result this feedback is about, if any.")
    useful: bool = Field(description="Was this result actually relevant/useful?")
    comment: str | None = None
    reviewer_id: str | None = Field(default=None, description="Caller-supplied, unauthenticated (Phase 11 FR-59).")


class RetrievalFeedbackResponse(BaseModel):
    status: str
    feedback_id: str


__all__ = [
    "DEFAULT_RESOLUTION_STATUS",
    "RetrievalIndexRequest",
    "RetrievalIndexResponse",
    "SimilarEmailMatch",
    "RetrievalSearchRequest",
    "RetrievalSearchResponse",
    "ResolutionStatusUpdateRequest",
    "ResolutionStatusUpdateResponse",
    "RetrievalFeedbackRequest",
    "RetrievalFeedbackResponse",
]
