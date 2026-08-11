"""
Manager Dashboard & Analytics endpoints (Module 11 / Phase 11, FR-53 to
FR-62).

Every GET here is a thin wrapper around app/services/dashboard_service.py
-- no raw aggregation queries in this file, per
docs/architecture_dashboard.md's "operational tables -> analytics/query
layer -> aggregated dashboard APIs" principle. `organization_id` defaults
to `"default"`, the same caller-supplied, unauthenticated trust model
every other endpoint in this codebase uses since Phase 1 -- not a new or
stronger identity claim.
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

from app.database.session import get_db
from app.models.feedback_event import (
    FEEDBACK_ACTIONS,  # noqa: F401 -- re-exported for API consumers/tests
)
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID
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
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> OverviewResponse:
    return OverviewResponse(**await dashboard_service.get_overview(db, organization_id, date_range))


@router.get("/email-volume", response_model=EmailVolumeResponse)
async def get_email_volume(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    granularity: str = Query(default="day", description="hour | day"),
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> EmailVolumeResponse:
    if granularity not in ("hour", "day"):
        raise HTTPException(status_code=422, detail="granularity must be 'hour' or 'day'.")
    return EmailVolumeResponse(**await dashboard_service.get_email_volume(db, organization_id, date_range, granularity))


@router.get("/categories", response_model=CategoryDistributionResponse)
async def get_categories(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> CategoryDistributionResponse:
    return CategoryDistributionResponse(**await dashboard_service.get_category_distribution(db, organization_id, date_range))


@router.get("/sentiment", response_model=SentimentTrendResponse)
async def get_sentiment(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> SentimentTrendResponse:
    return SentimentTrendResponse(**await dashboard_service.get_sentiment_trend(db, organization_id, date_range))


@router.get("/priority", response_model=PriorityDistributionResponse)
async def get_priority(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> PriorityDistributionResponse:
    return PriorityDistributionResponse(**await dashboard_service.get_priority_distribution(db, organization_id, date_range))


@router.get("/sla", response_model=SLAResponse)
async def get_sla(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> SLAResponse:
    return SLAResponse(**await dashboard_service.get_sla(db, organization_id, date_range))


@router.get("/agents", response_model=AgentWorkloadResponse)
async def get_agents(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> AgentWorkloadResponse:
    return AgentWorkloadResponse(**await dashboard_service.get_agent_workload(db, organization_id, date_range))


@router.get("/models", response_model=ModelQualityResponse)
async def get_models(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> ModelQualityResponse:
    return ModelQualityResponse(**await dashboard_service.get_model_quality(db, organization_id, date_range))


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue(
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueResponse:
    return ReviewQueueResponse(**await dashboard_service.get_review_queue(db, organization_id, limit))


@router.post("/review-queue/{prediction_id}/confirm", response_model=ReviewQueueConfirmResponse)
async def confirm_review_item(
    prediction_id: uuid.UUID,
    request: ReviewQueueConfirmRequest,
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueConfirmResponse:
    try:
        event = await dashboard_service.confirm_review_item(
            db,
            module=request.module,
            prediction_id=prediction_id,
            organization_id=organization_id,
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
    organization_id: str = DEFAULT_ORGANIZATION_ID,
    date_range: dashboard_service.DateRange = Depends(_date_range_dependency),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=422, detail="format must be 'csv' or 'pdf'.")

    data = await build_report_data(db, organization_id, date_range)

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
