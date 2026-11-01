"""
In-app notifications (FR-18; SLA-at-risk, drift and retraining alerts).
Read by the dashboard's notification bell, which polls -- the rows are
written by the agents process, which has no WebSocket of its own.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user
from app.database.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.admin import (
    NotificationListResponse,
    NotificationMarkReadRequest,
    NotificationMarkReadResponse,
    NotificationResponse,
)
from app.services.notification_service import count_unread, list_notifications, mark_read

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _to_response(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id,
        kind=n.kind,
        severity=n.severity,
        title=n.title,
        message=n.message,
        email_id=n.email_id,
        payload=n.payload,
        is_read=n.is_read,
        webhook_status=n.webhook_status,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    items = await list_notifications(db, current_user.organization_id, unread_only=unread_only, limit=limit)
    return NotificationListResponse(
        notifications=[_to_response(n) for n in items],
        unread_count=await count_unread(db, current_user.organization_id),
    )


@router.post("/read", response_model=NotificationMarkReadResponse)
async def mark_notifications_read(
    request: NotificationMarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationMarkReadResponse:
    updated = await mark_read(db, current_user.organization_id, request.notification_ids)
    return NotificationMarkReadResponse(updated=updated)
