"""
API response contracts for the routing engine (Module 8 / Phase 8, FR-37 to
FR-40).

`action` is a closed enum (auto_route/human_review/quarantine/fallback), not
a free-form string -- mirrors priority's closed `priority` label shape.
`supporting_signals`/`model_versions` are intentionally `dict`-typed rather
than fully-modeled sub-schemas: their per-signal shape already varies
(spam has `is_spam`+`confidence`, category has `top`+`confidence`, keywords
has `votes`), and each entry may be `None` when that upstream signal was
unavailable this call -- see app/services/routing_service.py.
"""

from typing import Literal

from pydantic import BaseModel, Field

RoutingAction = Literal["auto_route", "human_review", "quarantine", "fallback"]


class RoutingPredictionRequest(BaseModel):
    subject: str = Field(default="", description="Raw email subject line.")
    body: str = Field(..., description="Raw email body (HTML or plain text).")
    sender_email: str = Field(
        default="", description="Used for sender-domain classification only (FR-38)."
    )


class RoutingPredictionResponse(BaseModel):
    department: str | None = Field(
        description="One of app.routing.department_taxonomy.DEPARTMENTS, or None for quarantine."
    )
    action: RoutingAction
    confidence: float = Field(
        description=(
            "Category model confidence when department was chosen by category; a "
            "HEURISTIC keyword-vote share when chosen by keyword fallback; spam "
            "confidence for quarantine; 0.0 for the no-evidence fallback. Never a "
            "blended composite score -- see docs/routing_conflict_resolution.md "
            "'No Composite RoutingScore'."
        )
    )
    requires_human_review: bool
    reason: str = Field(description="Human-readable explanation, built from matched_rules.")
    matched_rules: list[str] = Field(description="Rule IDs from app.routing.rules.RULE_REGISTRY.")
    supporting_signals: dict = Field(
        description="Per-signal evidence + reliability label; entries are None if unavailable."
    )
    model_versions: dict[str, str | None]
    routing_rules_version: str
    keyword_matcher_version: str
    upstream_failures: list[str] = Field(
        description="Names of upstream services that failed/were unavailable this call."
    )
    processing_ms: float


class RoutingFeedbackRequest(BaseModel):
    subject: str = Field(default="")
    body: str
    predicted_department: str | None
    corrected_department: str | None
    predicted_action: RoutingAction
    corrected_action: RoutingAction | None = None
    comment: str | None = None
    reviewer_id: str | None = Field(default=None, description="Caller-supplied, unauthenticated (Phase 11 FR-59).")


class RoutingFeedbackResponse(BaseModel):
    status: str
    feedback_id: str
