"""
API contracts for Auto-Reply generation (Module 10 / Phase 10, FR-48 to
FR-52).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.reply_draft import DRAFT_STATUSES, GENERATION_POLICIES


class ReplyGenerateRequest(BaseModel):
    subject: str = Field(default="")
    body: str = Field(..., description="Raw current email body to draft a reply to.")
    sender_email: str = Field(default="")
    category: str | None = Field(default=None, description="Caller-supplied snapshot, e.g. from /categorization/predict.")
    department: str | None = Field(default=None, description="Caller-supplied snapshot, e.g. from /routing/predict.")
    source_email_id: uuid.UUID | None = Field(
        default=None, description="If this email is already a canonical EmailRecord (Phase 9). Not required."
    )
    # organization_id removed (Phase 20): it's derived from the
    # authenticated caller (current_user.organization_id) now, same fix
    # app/api/v1/endpoints/dashboard.py already got in Phase 17 -- this
    # endpoint was missed then. A caller-supplied org string here would
    # have let any signed-in user generate/read/approve/reject reply
    # drafts belonging to a DIFFERENT organization just by passing a
    # different value.


class ReplyDraftResponse(BaseModel):
    draft_id: uuid.UUID
    status: str = Field(description=f"One of {DRAFT_STATUSES}.")
    generation_policy: str = Field(description=f"One of {GENERATION_POLICIES}.")
    # Phase 20 addition: a reviewer needs to see what the draft is
    # actually replying to in order to judge it -- ReplyDraftResponse
    # previously carried only the generated text, with no way to see the
    # source email through the API at all.
    source_subject: str
    source_body: str
    generated_text: str | None
    edited_text: str | None
    edit_distance: int | None = Field(default=None, description="Levenshtein distance between generated_text and edited_text. Only set on EDIT.")
    retrieved_context_count: int
    retrieved_email_ids: list[str]
    llm_provider: str | None
    llm_model: str | None
    embedding_model: str | None
    retrieval_latency_ms: float | None
    llm_latency_ms: float | None
    total_latency_ms: float | None
    failure_reason: str | None
    created_at: datetime
    reviewed_at: datetime | None


class ReplyDraftListResponse(BaseModel):
    drafts: list[ReplyDraftResponse]


class ReplyEditRequest(BaseModel):
    edited_text: str = Field(..., min_length=1)
    reviewer_id: str | None = Field(default=None, description="No real auth yet -- caller-supplied, not verified.")


class ReplyReviewActionRequest(BaseModel):
    reviewer_id: str | None = Field(default=None, description="No real auth yet -- caller-supplied, not verified.")


class ReplyFeedbackRequest(BaseModel):
    draft_id: uuid.UUID
    useful: bool = Field(description="Was this draft a genuinely useful starting point?")
    comment: str | None = None
    reviewer_id: str | None = Field(default=None, description="Caller-supplied, unauthenticated (Phase 11 FR-59).")


class ReplyFeedbackResponse(BaseModel):
    status: str
    feedback_id: str


__all__ = [
    "ReplyGenerateRequest",
    "ReplyDraftResponse",
    "ReplyDraftListResponse",
    "ReplyEditRequest",
    "ReplyReviewActionRequest",
    "ReplyFeedbackRequest",
    "ReplyFeedbackResponse",
]
