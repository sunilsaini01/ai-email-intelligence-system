"""
Read/write access to per-organization settings
(app/models/organization_settings.py).

DEFAULT_SETTINGS is the contract: every key a caller may read is listed
here with its default, so `get_org_settings()` always returns a complete
dict and callers never need `.get(key, fallback)` scattered around.
Stored documents only hold what an admin actually changed.
"""

from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_settings import OrganizationSettings

ASSIGNMENT_NONE = "none"
ASSIGNMENT_ROUND_ROBIN = "round_robin"
ASSIGNMENT_SKILLS = "skills"
ASSIGNMENT_STRATEGIES = (ASSIGNMENT_NONE, ASSIGNMENT_ROUND_ROBIN, ASSIGNMENT_SKILLS)

DEFAULT_SETTINGS: dict = {
    # FR-18: outbound webhook for critical notifications (None = in-app only).
    "notification_webhook_url": None,
    "notify_on_critical": True,
    "notify_on_sla_at_risk": True,
    # FR-23: {model_label: {"display_name": str, "enabled": bool}}; labels
    # absent from it keep their model name and stay enabled.
    "category_taxonomy": {},
    # FR-42.
    "assignment_strategy": ASSIGNMENT_ROUND_ROBIN,
    # FR-41: {department: auto_route_threshold}, written only by
    # app/routing/feedback_weights.py, never by the admin API.
    "routing_thresholds": {},
    # GDPR retention -- None keeps data indefinitely.
    "data_retention_days": None,
    # FR-56.
    "weekly_reports_enabled": True,
}

# Keys only the system writes; the admin API rejects them.
SYSTEM_MANAGED_KEYS = frozenset({"routing_thresholds"})


def merge_with_defaults(stored: dict | None) -> dict:
    merged = deepcopy(DEFAULT_SETTINGS)
    for key, value in (stored or {}).items():
        if key in DEFAULT_SETTINGS:
            merged[key] = value
    return merged


async def get_org_settings(session: AsyncSession, organization_id: str) -> dict:
    row = await session.get(OrganizationSettings, organization_id)
    return merge_with_defaults(row.settings if row is not None else None)


async def update_org_settings(
    session: AsyncSession, organization_id: str, changes: dict, updated_by_user_id: str | None = None
) -> dict:
    """Shallow-merges `changes` into the stored document. Unknown keys are
    ignored rather than stored, so a typo can never silently become a
    setting nothing reads."""
    row = await session.get(OrganizationSettings, organization_id)
    stored = dict(row.settings) if row is not None else {}
    for key, value in changes.items():
        if key in DEFAULT_SETTINGS:
            stored[key] = value

    if row is None:
        row = OrganizationSettings(organization_id=organization_id, settings=stored)
        session.add(row)
    else:
        # Reassign, don't mutate in place -- SQLAlchemy does not track
        # in-place mutation of a plain JSON column.
        row.settings = stored
    row.updated_by_user_id = updated_by_user_id
    await session.commit()
    return merge_with_defaults(stored)
