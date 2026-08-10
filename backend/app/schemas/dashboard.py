"""
API contracts for the Manager Dashboard & Analytics (Module 11 / Phase 11,
FR-53 to FR-62).

`EvidenceBadge` exists on every response that carries a model-derived
number specifically so the frontend never has to guess whether a count is
backed by validated evidence -- see docs/architecture_dashboard.md "Model
evidence policy" and the master prompt's own explicit instruction not to
present synthetic/off-domain metrics as production accuracy.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvidenceBadge(BaseModel):
    status: str = Field(description="REAL_VALIDATED | SYNTHETIC | OFF_DOMAIN | UNVALIDATED | PROVISIONAL")
    note: str


class OverviewResponse(BaseModel):
    total_emails_proxy: int = Field(description="Spam module's row count in range -- the closest available traffic proxy. See `note`.")
    emails_per_day_avg: float
    spam_rate: float | None
    high_critical_priority_count: int
    sla_breach_count: int
    pending_human_reviews: int
    feedback_correction_rate: float | None
    reviewed_feedback_count: int
    auto_reply_acceptance_rate: float | None
    auto_reply_reviewed_count: int
    date_range_start: datetime
    date_range_end: datetime
    note: str


class VolumePoint(BaseModel):
    bucket: str
    count: int


class EmailVolumeResponse(BaseModel):
    granularity: str
    points: list[VolumePoint]
    total: int
    note: str


class CategoryCount(BaseModel):
    category: str
    count: int


class CategoryDistributionResponse(BaseModel):
    counts: list[CategoryCount]
    evidence: EvidenceBadge


class SentimentPoint(BaseModel):
    bucket: str
    sentiment: str
    count: int


class SentimentTrendResponse(BaseModel):
    points: list[SentimentPoint]
    evidence: EvidenceBadge


class PriorityCount(BaseModel):
    priority: str
    count: int


class PriorityDistributionResponse(BaseModel):
    counts: list[PriorityCount]
    evidence: EvidenceBadge


class SLABucket(BaseModel):
    priority: str
    within_sla: int
    at_risk: int
    breached: int


class SLAResponse(BaseModel):
    buckets: list[SLABucket]
    excluded_no_priority: int
    sla_targets_hours: dict[str, float]
    note: str


class AgentWorkload(BaseModel):
    reviewer_id: str
    assigned: int
    pending: int
    resolved: int
    avg_resolution_minutes: float | None


class AgentWorkloadResponse(BaseModel):
    agents: list[AgentWorkload]
    note: str


class ModelQualityEntry(BaseModel):
    module: str
    evidence: EvidenceBadge
    offline_reference_metric: str | None
    correction_rate: float | None
    reviewed_count: int
    corrected_count: int
    retraining_threshold_reached: bool


class ModelQualityResponse(BaseModel):
    modules: list[ModelQualityEntry]


class ReviewQueueItem(BaseModel):
    prediction_id: str
    module: str
    subject: str
    confidence: float
    predicted_value: Any
    urgency_score: float
    created_at: datetime
    evidence: EvidenceBadge


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    note: str


class ReviewQueueConfirmRequest(BaseModel):
    module: str
    subject: str = Field(default="")
    body: str = Field(default="")
    predicted_value: Any = None
    confidence: float | None = None
    reviewer_id: str | None = None


class ReviewQueueConfirmResponse(BaseModel):
    status: str
    feedback_id: str


class ReportExportRequest(BaseModel):
    format: str = Field(description="'csv' or 'pdf'")


__all__ = [
    "EvidenceBadge",
    "OverviewResponse",
    "VolumePoint",
    "EmailVolumeResponse",
    "CategoryCount",
    "CategoryDistributionResponse",
    "SentimentPoint",
    "SentimentTrendResponse",
    "PriorityCount",
    "PriorityDistributionResponse",
    "SLABucket",
    "SLAResponse",
    "AgentWorkload",
    "AgentWorkloadResponse",
    "ModelQualityEntry",
    "ModelQualityResponse",
    "ReviewQueueItem",
    "ReviewQueueResponse",
    "ReviewQueueConfirmRequest",
    "ReviewQueueConfirmResponse",
    "ReportExportRequest",
]
