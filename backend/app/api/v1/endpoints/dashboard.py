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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user, require_manager, user_for_token
from app.database.session import get_db
from app.models.feedback_event import (
    FEEDBACK_ACTIONS,  # noqa: F401 -- re-exported for API consumers/tests
)
from app.models.generated_report import GeneratedReport
from app.models.user import User
from app.schemas.admin import (
    GeneratedReportListResponse,
    GeneratedReportResponse,
    SenderSentimentResponse,
)
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
from app.services.sender_sentiment_service import WINDOW_DAYS as SENDER_WINDOW_DAYS
from app.services.sender_sentiment_service import get_sender_trends

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
            reviewer_id=str(current_user.id),
        )
    except dashboard_service.AlreadyReviewedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    broadcaster = get_dashboard_broadcaster()
    await broadcaster.broadcast(
        "review_queue_confirmed",
        {"prediction_id": str(prediction_id), "module": request.module},
        organization_id=current_user.organization_id,
    )
    return ReviewQueueConfirmResponse(status="logged", feedback_id=str(event.id))


@router.get("/reports/export")
async def export_report(
    format: str = Query(description="'csv' or 'pdf'"),
    current_user: User = Depends(require_manager),
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


@router.get("/reports/generated", response_model=GeneratedReportListResponse)
async def list_generated_reports(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
) -> GeneratedReportListResponse:
    """FR-56: the weekly reports the agents process generates
    (app/services/scheduled_jobs.py generate_weekly_reports)."""
    rows = (
        await db.execute(
            select(
                GeneratedReport.id,
                GeneratedReport.period_start,
                GeneratedReport.period_end,
                GeneratedReport.report_format,
                func.length(GeneratedReport.content),
                GeneratedReport.created_at,
            )
            .where(GeneratedReport.organization_id == current_user.organization_id)
            .order_by(GeneratedReport.period_start.desc(), GeneratedReport.report_format)
            .limit(limit)
        )
    ).all()
    return GeneratedReportListResponse(
        reports=[
            GeneratedReportResponse(
                id=r[0], period_start=r[1], period_end=r[2], report_format=r[3], size_bytes=r[4] or 0, created_at=r[5]
            )
            for r in rows
        ]
    )


@router.get("/reports/generated/{report_id}")
async def download_generated_report(
    report_id: uuid.UUID,
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
) -> Response:
    report = await db.get(GeneratedReport, report_id)
    if report is None or report.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Report not found.")
    media_type = "text/csv" if report.report_format == "csv" else "application/pdf"
    filename = f"weekly_report_{report.period_start:%Y-%m-%d}.{report.report_format}"
    return Response(
        content=report.content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/sentiment/senders", response_model=SenderSentimentResponse)
async def sender_sentiment_trends(
    sender_email: str | None = Query(default=None, description="Restrict to one sender."),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SenderSentimentResponse:
    """FR-32: per-sender sentiment trends, escalation candidates first."""
    senders = await get_sender_trends(db, current_user.organization_id, sender_email=sender_email, limit=limit)
    return SenderSentimentResponse(senders=senders, window_days=SENDER_WINDOW_DAYS)


# The live-update socket is NOT on `router`: app/api/v1/router.py puts
# `router` under protected_router, whose get_current_user dependency reads
# an Authorization header via OAuth2PasswordBearer -- which crashes on a
# WebSocket (no Request object) and which browsers can't send on a
# WebSocket anyway. Since Phase 17 that made every connection fail with a
# TypeError and the dashboard silently fell back to 30s polling.
# `ws_router` stays outside protected_router and authenticates itself.
ws_router = APIRouter(prefix="/dashboard", tags=["Manager Dashboard & Analytics"])

# Browsers can only attach credentials to a WebSocket through the URL or
# the Sec-WebSocket-Protocol header. The URL would put the token into
# access logs, so the client sends two subprotocol values instead:
# "bearer" and the token itself; the server echoes back only "bearer".
WS_AUTH_SUBPROTOCOL = "bearer"
WS_POLICY_VIOLATION = 1008


def _token_from_subprotocols(websocket: WebSocket) -> str | None:
    offered = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    if len(offered) == 2 and offered[0] == WS_AUTH_SUBPROTOCOL:
        return offered[1]
    return None


@ws_router.websocket("/ws")
async def dashboard_websocket(
    websocket: WebSocket,
    broadcaster: DashboardBroadcaster = Depends(get_dashboard_broadcaster),
    db: AsyncSession = Depends(get_db),
) -> None:
    """FR-54. In-process fan-out only -- see
    app/services/dashboard_broadcaster.py's module docstring for the
    documented single-process scaling limit. The client's 30s polling
    fallback (Stage 7) is what makes that limit degrade gracefully
    instead of silently under-delivering updates.

    Same identity rules as every HTTP endpoint (user_for_token: valid
    token, existing and active user); events are delivered only for the
    user's own organization."""
    user = await user_for_token(_token_from_subprotocols(websocket), db)
    if user is None:
        # Closing before accept() rejects the handshake (HTTP 403).
        await websocket.close(code=WS_POLICY_VIOLATION)
        return
    organization_id = user.organization_id
    # The DB session isn't needed while the socket idles; don't hold it.
    await db.close()

    await broadcaster.connect(websocket, organization_id, subprotocol=WS_AUTH_SUBPROTOCOL)
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
