"""
Notifications (FR-18: "Critical emails shall trigger immediate
notifications (in-app + configurable webhook)"; PRD Epic 2: SLA alerts
before the breach, not after).

`notify()` writes the in-app row first, then -- if the organization has a
webhook configured -- POSTs a small JSON payload to it and records the
outcome on the same row. The webhook payload deliberately carries no
email body: the receiving system (Slack, PagerDuty, a ticketing tool) is
outside this project's PII boundary (FR-09's reasoning applied to a
different outbound channel), so it gets the anonymized subject line, the
priority, the department and a link-back id only.

Webhook delivery is best-effort with a short timeout: a slow or broken
receiver must never stall the pipeline that raised the notification.
"""

import logging
import uuid

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import (
    KIND_CRITICAL_EMAIL,
    WEBHOOK_DELIVERED,
    WEBHOOK_FAILED,
    WEBHOOK_NOT_CONFIGURED,
    Notification,
)
from app.security.pii_anonymizer import anonymize_email_body
from app.services.organization_settings_service import get_org_settings

logger = logging.getLogger("app.notifications")

WEBHOOK_TIMEOUT_SECONDS = 5.0


def safe_subject(subject: str) -> str:
    subject = (subject or "").strip()
    if not subject:
        return "(no subject)"
    try:
        return anonymize_email_body(subject)[0][:200]
    except Exception:
        # Presidio unavailable -> say nothing about the subject rather than
        # leak it unanonymized.
        logger.warning("notification_subject_anonymize_failed", exc_info=True)
        return "(subject withheld)"


async def _deliver_webhook(url: str, payload: dict) -> str:
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        return WEBHOOK_DELIVERED
    except Exception:
        logger.warning("notification_webhook_failed", exc_info=True, extra={"kind": payload.get("kind")})
        return WEBHOOK_FAILED


async def notify(
    session: AsyncSession,
    organization_id: str,
    kind: str,
    title: str,
    message: str = "",
    severity: str = "critical",
    email_id: uuid.UUID | None = None,
    dedup_key: str | None = None,
    payload: dict | None = None,
    send_webhook: bool = True,
) -> Notification | None:
    """Returns None (and writes nothing) when `dedup_key` was already
    notified for this organization."""
    if dedup_key is not None:
        existing = await session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.organization_id == organization_id, Notification.dedup_key == dedup_key)
        )
        if existing.scalar_one() > 0:
            return None

    notification = Notification(
        organization_id=organization_id,
        kind=kind,
        severity=severity,
        title=title,
        message=message,
        email_id=email_id,
        dedup_key=dedup_key,
        payload=payload,
    )
    session.add(notification)
    await session.commit()
    await session.refresh(notification)

    settings = await get_org_settings(session, organization_id)
    webhook_url = settings["notification_webhook_url"]
    if send_webhook and webhook_url:
        notification.webhook_status = await _deliver_webhook(
            webhook_url,
            {
                "id": str(notification.id),
                "kind": kind,
                "severity": severity,
                "title": title,
                "message": message,
                "email_id": str(email_id) if email_id else None,
                "organization_id": organization_id,
                "created_at": notification.created_at.isoformat(),
                **(payload or {}),
            },
        )
    else:
        notification.webhook_status = WEBHOOK_NOT_CONFIGURED
    await session.commit()

    logger.info(
        "notification_created",
        extra={"kind": kind, "severity": severity, "webhook_status": notification.webhook_status},
    )
    return notification


async def notify_critical_email(
    session: AsyncSession,
    organization_id: str,
    email_id: uuid.UUID | None,
    subject: str,
    department: str | None,
    reasons: list[str] | None = None,
) -> Notification | None:
    settings = await get_org_settings(session, organization_id)
    if not settings["notify_on_critical"]:
        return None
    subject_line = safe_subject(subject)
    message = f"Routed to {department or 'human triage'}."
    if reasons:
        message = f"{message} {' '.join(reasons)}"
    return await notify(
        session,
        organization_id,
        kind=KIND_CRITICAL_EMAIL,
        title=f"Critical email: {subject_line}",
        message=message,
        severity="critical",
        email_id=email_id,
        dedup_key=f"{KIND_CRITICAL_EMAIL}:{email_id}" if email_id else None,
        payload={"priority": "Critical", "department": department, "subject": subject_line},
    )


async def list_notifications(
    session: AsyncSession, organization_id: str, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    query = select(Notification).where(Notification.organization_id == organization_id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    query = query.order_by(Notification.created_at.desc()).limit(limit)
    return list((await session.execute(query)).scalars())


async def count_unread(session: AsyncSession, organization_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.organization_id == organization_id, Notification.is_read.is_(False))
    )
    return result.scalar_one()


async def mark_read(session: AsyncSession, organization_id: str, notification_ids: list[uuid.UUID] | None) -> int:
    """`notification_ids=None` marks everything read."""
    statement = update(Notification).where(
        Notification.organization_id == organization_id, Notification.is_read.is_(False)
    )
    if notification_ids is not None:
        statement = statement.where(Notification.id.in_(notification_ids))
    result = await session.execute(statement.values(is_read=True))
    await session.commit()
    return result.rowcount or 0
