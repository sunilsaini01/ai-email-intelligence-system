"""API contracts for the Phase 22 admin, notification, model-operations and
privacy endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, HttpUrl

from app.models.user import USER_ROLES
from app.services.organization_settings_service import ASSIGNMENT_STRATEGIES


class OrganizationSettingsResponse(BaseModel):
    notification_webhook_url: str | None
    notify_on_critical: bool
    notify_on_sla_at_risk: bool
    category_taxonomy: dict
    assignment_strategy: str
    routing_thresholds: dict[str, float] = Field(
        description="FR-41: learned from routing feedback; read-only, never set through this API."
    )
    data_retention_days: int | None
    weekly_reports_enabled: bool


class OrganizationSettingsUpdate(BaseModel):
    """Every field optional -- only the ones sent are changed."""

    notification_webhook_url: HttpUrl | None = None
    notify_on_critical: bool | None = None
    notify_on_sla_at_risk: bool | None = None
    assignment_strategy: str | None = Field(default=None, description=f"One of {ASSIGNMENT_STRATEGIES}.")
    data_retention_days: int | None = Field(default=None, ge=1, le=3650)
    weekly_reports_enabled: bool | None = None
    clear_webhook: bool = Field(default=False, description="Remove the configured webhook URL.")
    clear_retention: bool = Field(default=False, description="Keep data indefinitely again.")


class CategoryTaxonomyEntry(BaseModel):
    label: str
    display_name: str
    enabled: bool
    can_disable: bool = True


class CategoryTaxonomyResponse(BaseModel):
    categories: list[CategoryTaxonomyEntry]
    note: str = (
        "Labels are the category model's fixed FR-21 set. Organizations can rename or disable them; "
        "adding a brand-new category requires retraining the model."
    )


class CategoryTaxonomyUpdateEntry(BaseModel):
    label: str
    display_name: str | None = Field(default=None, max_length=100)
    enabled: bool = True


class CategoryTaxonomyUpdate(BaseModel):
    categories: list[CategoryTaxonomyUpdateEntry]


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    department: str | None
    skills: list[str]
    is_active: bool
    # organization_creator | invitation | admin_verified | legacy_unverified
    # -- see docs/security/organization_membership_remediation.md.
    membership_source: str
    last_assigned_at: datetime | None
    created_at: datetime


class AdminUserListResponse(BaseModel):
    users: list[AdminUserResponse]


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, description=f"One of {USER_ROLES}.")
    department: str | None = None
    skills: list[str] | None = None
    is_active: bool | None = None
    clear_department: bool = False
    confirm_membership: bool = Field(
        default=False, description="Mark a legacy_unverified account as reviewed and legitimate (admin_verified)."
    )


class DataSubjectErasureRequest(BaseModel):
    sender_email: EmailStr
    confirm: bool = Field(description="Must be true -- erasure is permanent and cannot be undone.")


class DataSubjectErasureResponse(BaseModel):
    status: str
    deleted: dict[str, int]


class NotificationResponse(BaseModel):
    id: uuid.UUID
    kind: str
    severity: str
    title: str
    message: str
    email_id: uuid.UUID | None
    payload: dict | None
    is_read: bool
    webhook_status: str
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    unread_count: int


class NotificationMarkReadRequest(BaseModel):
    notification_ids: list[uuid.UUID] | None = Field(default=None, description="Omit to mark all as read.")


class NotificationMarkReadResponse(BaseModel):
    updated: int


class RetrainingTriggerResponse(BaseModel):
    id: uuid.UUID
    module: str
    status: str
    source: str
    feedback_count_at_trigger: int
    threshold_used: int
    requested_by_user_id: str | None
    triggered_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result_message: str | None


class RetrainingTriggerListResponse(BaseModel):
    triggers: list[RetrainingTriggerResponse]


class RetrainRequest(BaseModel):
    module: str


class DriftModuleResponse(BaseModel):
    module: str
    psi: float | None
    prediction_status: str
    baseline_count: int
    current_count: int
    baseline_correction_rate: float | None
    current_correction_rate: float | None
    performance_drift: bool
    alert: bool
    baseline_distribution: dict
    current_distribution: dict


class DriftResponse(BaseModel):
    modules: list[DriftModuleResponse]
    current_window_days: int
    baseline_window_days: int
    note: str


class GeneratedReportResponse(BaseModel):
    id: uuid.UUID
    period_start: datetime
    period_end: datetime
    report_format: str
    size_bytes: int
    created_at: datetime


class GeneratedReportListResponse(BaseModel):
    reports: list[GeneratedReportResponse]


class SenderSentimentPoint(BaseModel):
    date: str
    average_score: float
    count: int


class SenderSentimentTrend(BaseModel):
    sender_email: str
    email_count: int
    negative_count: int
    average_score: float
    recent_average_score: float
    trend: str  # improving | stable | declining
    escalation_candidate: bool
    points: list[SenderSentimentPoint]


class SenderSentimentResponse(BaseModel):
    senders: list[SenderSentimentTrend]
    window_days: int
