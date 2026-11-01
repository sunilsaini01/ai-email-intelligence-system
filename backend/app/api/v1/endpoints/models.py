"""
Model operations (PRD SS13.2 "Model Management"; FR-61, FR-72; PRD Epic 4
"trigger model retraining from the dashboard without touching the
terminal").

POST /models/retrain only QUEUES a retraining_triggers row; the agents
process executes it (app/mlops/retraining_runner.py) and registers an
MLflow candidate. Promotion to production stays the explicit, regression-
checked scripts/mlops/promote_model.py step (FR-71) -- deliberately not
exposed as a one-click HTTP action.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import require_admin, require_manager
from app.database.repositories.feedback_event_repository import FeedbackEventRepository
from app.database.repositories.retraining_trigger_repository import RetrainingTriggerRepository
from app.database.session import get_db
from app.mlops.drift import BASELINE_WINDOW_DAYS, CURRENT_WINDOW_DAYS
from app.mlops.retraining_runner import NOT_RETRAINABLE, TRAINING_SCRIPTS
from app.models.retraining_trigger import RetrainingTrigger
from app.models.user import User
from app.schemas.admin import (
    DriftModuleResponse,
    DriftResponse,
    RetrainingTriggerListResponse,
    RetrainingTriggerResponse,
    RetrainRequest,
)
from app.services.drift_service import compute_drift

router = APIRouter(prefix="/models", tags=["Model Management"])


def _trigger_response(t: RetrainingTrigger) -> RetrainingTriggerResponse:
    return RetrainingTriggerResponse(
        id=t.id,
        module=t.module,
        status=t.status,
        source=t.source,
        feedback_count_at_trigger=t.feedback_count_at_trigger,
        threshold_used=t.threshold_used,
        requested_by_user_id=t.requested_by_user_id,
        triggered_at=t.triggered_at,
        started_at=t.started_at,
        completed_at=t.completed_at,
        result_message=t.result_message,
    )


@router.get("/retraining", response_model=RetrainingTriggerListResponse)
async def list_retraining(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_manager),
    db: AsyncSession = Depends(get_db),
) -> RetrainingTriggerListResponse:
    triggers = await RetrainingTriggerRepository(db).list_recent(limit=limit)
    return RetrainingTriggerListResponse(triggers=[_trigger_response(t) for t in triggers])


@router.post("/retrain", response_model=RetrainingTriggerResponse, status_code=202)
async def request_retraining(
    request: RetrainRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RetrainingTriggerResponse:
    if request.module not in TRAINING_SCRIPTS:
        reason = NOT_RETRAINABLE.get(request.module, f"Unknown module; retrainable modules are {sorted(TRAINING_SCRIPTS)}.")
        raise HTTPException(status_code=422, detail=reason)

    repo = RetrainingTriggerRepository(db)
    if await repo.has_open_trigger(request.module):
        raise HTTPException(status_code=409, detail=f"A retraining run for '{request.module}' is already queued or running.")

    latest = await repo.get_latest(request.module)
    corrections = await FeedbackEventRepository(db).count_corrections_since(
        request.module, latest.triggered_at if latest is not None else None
    )
    trigger = await repo.create(
        module=request.module,
        feedback_count_at_trigger=corrections,
        threshold_used=0,
        source="manual",
        requested_by_user_id=str(current_user.id),
    )
    return _trigger_response(trigger)


@router.get("/drift", response_model=DriftResponse)
async def get_drift(
    current_user: User = Depends(require_manager), db: AsyncSession = Depends(get_db)
) -> DriftResponse:
    drift = await compute_drift(db, current_user.organization_id)
    return DriftResponse(
        modules=[DriftModuleResponse(**d.as_dict()) for d in drift],
        current_window_days=CURRENT_WINDOW_DAYS,
        baseline_window_days=BASELINE_WINDOW_DAYS,
        note=(
            "Prediction drift is the PSI of predicted-label distributions; performance drift is a rise of more "
            "than 5 points in the feedback correction rate. Input-feature drift is not measured. See app/mlops/drift.py."
        ),
    )
