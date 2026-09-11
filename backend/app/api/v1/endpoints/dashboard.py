"""
Manager Dashboard & Analytics endpoints (Module 11 / Phase 11, FR-53 to
FR-62).

Every GET here is a thin wrapper around app/services/dashboard_service.py
-- no raw aggregation queries in this file, per
docs/architecture_dashboard.md's "operational tables -> analytics/query
layer -> aggregated dashboard APIs" principle.

`organization_id` is Phase 17's real fix for the gap this file's own
docstring used to name explicitly: it no longer comes from a caller-
supplied query parameter (any caller could ask for any organization's
data by just changing a string) -- it's read off `current_user`, injected
by `get_current_user` and already verified real by the JWT that dependency
requires (see app/api/v1/router.py's `protected_router` for where that
requirement is enforced at the router level; the `Depends(get_current_user)`
on each function below reuses that same per-request result via FastAPI's
dependency caching, it does not re-authenticate).
"""

import logging
import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user
from app.database.session import get_db
from app.models.feedback_event import (
    FEEDBACK_ACTIONS,  # noqa: F401 -- re-exported for API consumers/tests
)
from app.models.user import User
from app.schemas.dashboard import (
    AgentWorkloadResponse,
    CategoryDistributionResponse,
    EmailVolumeResponse,
    ModelQualityResponse,
    OverviewResponse,
    PriorityDistributionResponse,
    ReviewQueueConfirmRequest,
    ReviewQueueConfirmResponse,
    ReviewQueueResponse,
    SentimentTrendResponse,
    SLAResponse,
)
from app.services import dashboard_service
from app.services.dashboard_broadcaster import DashboardBroadcaster, get_dashboard_broadcaster
from app.services.dashboard_report_export import build_report_data, export_csv, export_pdf

router = APIRouter(prefix="/dashboard", tags=["Manager Dashboard & Analytics"])
logger = logging.getLogger("app.dashboard")


def _date_range_dependency(
    range: str = Query(default="today", description="today | week | month | custom"),
    start: datetime | None = Query(default=None, description="Required if range=custom."),
    end: datetime | None = Query(default=None, description="Required if range=custom."),
) -> dashboard_service.DateRange:
    try:
        return dashboard_service.resolve_date_range(range, start, end)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> OverviewResponse:
    return OverviewResponse(**await dashboard_service.get_overview(db, current_user.organization_id, date_range))


@router.get("/email-volume", response_model=EmailVolumeResponse)
async def get_email_volume(
    current_user: User = Depends(get_current_user),
    granularity: str = Query(default="day", description="hour | day"),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> EmailVolumeResponse:
    if granularity not in ("hour", "day"):
        raise HTTPException(status_code=422, detail="granularity must be 'hour' or 'day'.")
    return EmailVolumeResponse(
        **await dashboard_service.get_email_volume(db, current_user.organization_id, date_range, granularity)
    )


@router.get("/categories", response_model=CategoryDistributionResponse)
async def get_categories(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> CategoryDistributionResponse:
    return CategoryDistributionResponse(**await dashboard_service.get_category_distribution(db, current_user.organization_id, date_range))


@router.get("/sentiment", response_model=SentimentTrendResponse)
async def get_sentiment(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> SentimentTrendResponse:
    return SentimentTrendResponse(**await dashboard_service.get_sentiment_trend(db, current_user.organization_id, date_range))


@router.get("/priority", response_model=PriorityDistributionResponse)
async def get_priority(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> PriorityDistributionResponse:
    return PriorityDistributionResponse(**await dashboard_service.get_priority_distribution(db, current_user.organization_id, date_range))


@router.get("/sla", response_model=SLAResponse)
async def get_sla(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> SLAResponse:
    return SLAResponse(**await dashboard_service.get_sla(db, current_user.organization_id, date_range))


@router.get("/agents", response_model=AgentWorkloadResponse)
async def get_agents(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkloadResponse:
    return AgentWorkloadResponse(**await dashboard_service.get_agent_workload(db, current_user.organization_id, date_range))


@router.get("/models", response_model=ModelQualityResponse)
async def get_models(
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> ModelQualityResponse:
    return ModelQualityResponse(**await dashboard_service.get_model_quality(db, current_user.organization_id, date_range))


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueResponse:
    return ReviewQueueResponse(**await dashboard_service.get_review_queue(db, current_user.organization_id, limit))


@router.post("/review-queue/{prediction_id}/confirm", response_model=ReviewQueueConfirmResponse)
async def confirm_review_item(
    prediction_id: uuid.UUID,
    request: ReviewQueueConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueConfirmResponse:
    try:
        event = await dashboard_service.confirm_review_item(
            db,
            module=request.module,
            prediction_id=prediction_id,
            organization_id=current_user.organization_id,
            subject=request.subject,
            predicted_value=request.predicted_value,
            confidence=request.confidence,
            reviewer_id=request.reviewer_id,
        )
    except dashboard_service.AlreadyReviewedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    broadcaster = get_dashboard_broadcaster()
    await broadcaster.broadcast("review_queue_confirmed", {"prediction_id": str(prediction_id), "module": request.module})
    return ReviewQueueConfirmResponse(status="logged", feedback_id=str(event.id))


@router.get("/reports/export")
async def export_report(
    format: str = Query(description="'csv' or 'pdf'"),
    current_user: User = Depends(get_current_user),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=422, detail="format must be 'csv' or 'pdf'.")

    data = await build_report_data(db, current_user.organization_id, date_range)

    if format == "csv":
        content = export_csv(data)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=email_intelligence_report.csv"},
        )

    content = export_pdf(data)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=email_intelligence_report.pdf"},
    )


@router.websocket("/ws")
async def dashboard_websocket(
    websocket: WebSocket,
    broadcaster: DashboardBroadcaster = Depends(get_dashboard_broadcaster),
) -> None:
    """FR-54. In-process fan-out only -- see
    app/services/dashboard_broadcaster.py's module docstring for the
    documented single-process scaling limit. The client's 30s polling
    fallback (Stage 7) is what makes that limit degrade gracefully
    instead of silently under-delivering updates."""
    await broadcaster.connect(websocket)
    try:
        while True:
            # This endpoint is push-only from the server's side; it still
            # awaits incoming frames so a client disconnect is detected
            # promptly (FastAPI/Starlette's WebSocket has no "accept and
            # never read" idle mode that also detects disconnects).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(websocket)
