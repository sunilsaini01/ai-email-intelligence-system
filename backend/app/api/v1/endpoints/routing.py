"""
Routing engine endpoints (Module 8 / Phase 8, FR-37 to FR-40).

No 503/ServiceUnavailable wrapper, unlike spam/priority/category/intent --
RoutingService has no artifact of its own to be missing (same reasoning as
sentiment.py/summarization.py). Its five upstream services' own
unavailability is handled INSIDE RoutingService.route() via per-signal
try/except, not surfaced as an HTTP error here -- see
app/services/routing_service.py's module docstring. /predict therefore
always returns 200 with a decision (worst case: General + human review),
per RULE 10 "never silently drop an email."

Same run_in_threadpool + bounded, best-effort DB write pattern as every
other module (see app/database/session.py's DB_WRITE_TIMEOUT_SECONDS
docstring).
"""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user, require_admin
from app.database.repositories.routing_decision_repository import RoutingDecisionRepository
from app.database.repositories.routing_override_repository import RoutingOverrideRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.models.feedback_event import ACTION_CORRECTION
from app.models.routing_override import RoutingOverride
from app.models.user import User
from app.schemas.routing import (
    RoutingFeedbackRequest,
    RoutingFeedbackResponse,
    RoutingPredictionRequest,
    RoutingPredictionResponse,
)
from app.schemas.routing_override import (
    RoutingOverrideCreateRequest,
    RoutingOverrideListResponse,
    RoutingOverrideResponse,
    RoutingOverrideUpdateRequest,
)
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_routing_feedback_logger
from app.services.routing_override_service import apply_organization_overrides
from app.services.routing_service import RoutingService, get_routing_service

router = APIRouter(prefix="/routing", tags=["Email Routing"])

logger = logging.getLogger("app.routing")


@router.post("/predict", response_model=RoutingPredictionResponse)
async def predict_routing(
    request: RoutingPredictionRequest,
    current_user: User = Depends(get_current_user),
    service: RoutingService = Depends(get_routing_service),
    db: AsyncSession = Depends(get_db),
) -> RoutingPredictionResponse:
    result = await run_in_threadpool(
        service.route,
        subject=request.subject,
        body=request.body,
        sender_email=request.sender_email,
    )

    # Phase 21: admin-configurable overrides (app/routing/overrides.py) are
    # a final pass over the base engine's decision -- applied here, not
    # inside RoutingService.route() itself, since that function is a
    # synchronous, DB-free composition step shared with the Orchestrator's
    # own call site (app/agents/orchestrator.py._finalize_workflow), which
    # applies this same step separately after its own route() call.
    result = await apply_organization_overrides(
        db, current_user.organization_id, result, request.subject, request.body, request.sender_email
    )

    logger.info(
        "routing_decision",
        extra={
            "department": result["department"],
            "action": result["action"],
            "requires_human_review": result["requires_human_review"],
            "matched_rules": result["matched_rules"],
            "upstream_failures": result["upstream_failures"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = RoutingDecisionRepository(db)
        await asyncio.wait_for(
            repository.log_decision(
                organization_id=current_user.organization_id,
                subject=request.subject,
                body=request.body,
                department=result["department"],
                action=result["action"],
                confidence=result["confidence"],
                requires_human_review=result["requires_human_review"],
                reason=result["reason"],
                matched_rules=result["matched_rules"],
                supporting_signals=result["supporting_signals"],
                model_versions=result["model_versions"],
                routing_rules_version=result["routing_rules_version"],
                keyword_matcher_version=result["keyword_matcher_version"],
                upstream_failures=result["upstream_failures"],
                processing_ms=result["processing_ms"],
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("routing_decision_log_failed", exc_info=True)

    return RoutingPredictionResponse(**result)


@router.post("/feedback", response_model=RoutingFeedbackResponse)
async def submit_routing_feedback(
    request: RoutingFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_routing_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> RoutingFeedbackResponse:
    feedback_id = feedback_logger.log_routing_feedback(
        subject=request.subject,
        body=request.body,
        predicted_department=request.predicted_department,
        corrected_department=request.corrected_department,
        predicted_action=request.predicted_action,
        corrected_action=request.corrected_action,
        comment=request.comment,
    )

    try:
        await record_feedback_event(
            db,
            module="routing",
            action=ACTION_CORRECTION,
            original_value={"department": request.predicted_department, "action": request.predicted_action},
            corrected_value={"department": request.corrected_department, "action": request.corrected_action},
            reviewer_id=request.reviewer_id,
            reason=request.comment,
        )
    except Exception:
        logger.warning("routing_feedback_event_log_failed", exc_info=True)

    return RoutingFeedbackResponse(status="logged", feedback_id=feedback_id)


# --- Phase 21: admin-configurable routing overrides --------------------
# Read (list) stays open to any signed-in member -- same read-open/
# write-admin split Phase 19 established for mailbox connections; knowing
# which overrides are active is ordinary situational awareness for anyone
# reading a routing decision's matched_rules, not configuration.


def _override_to_response(override: RoutingOverride) -> RoutingOverrideResponse:
    return RoutingOverrideResponse(
        id=override.id,
        name=override.name,
        priority_order=override.priority_order,
        is_active=override.is_active,
        conditions=override.conditions,
        override_department=override.override_department,
        override_action=override.override_action,
        override_requires_human_review=override.override_requires_human_review,
        created_at=override.created_at,
        updated_at=override.updated_at,
    )


@router.get("/overrides", response_model=RoutingOverrideListResponse)
async def list_routing_overrides(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoutingOverrideListResponse:
    overrides = await RoutingOverrideRepository(db).list_for_organization(current_user.organization_id)
    return RoutingOverrideListResponse(overrides=[_override_to_response(o) for o in overrides])


@router.post("/overrides", response_model=RoutingOverrideResponse, status_code=201)
async def create_routing_override(
    request: RoutingOverrideCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoutingOverrideResponse:
    override = await RoutingOverrideRepository(db).create(
        organization_id=current_user.organization_id,
        created_by_user_id=current_user.id,
        name=request.name,
        priority_order=request.priority_order,
        is_active=request.is_active,
        conditions=[c.model_dump() for c in request.conditions],
        override_department=request.override_department,
        override_action=request.override_action,
        override_requires_human_review=request.override_requires_human_review,
    )
    return _override_to_response(override)


@router.put("/overrides/{override_id}", response_model=RoutingOverrideResponse)
async def update_routing_override(
    override_id: uuid.UUID,
    request: RoutingOverrideUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> RoutingOverrideResponse:
    repository = RoutingOverrideRepository(db)
    override = await repository.get_by_id(current_user.organization_id, override_id)
    if override is None:
        raise HTTPException(status_code=404, detail="Routing override not found.")

    # model_dump(exclude_unset=True) already recurses into nested models
    # (conditions becomes a plain list[dict], matching the JSON column
    # shape) and, critically, omits any field the caller didn't include in
    # the request body at all -- see RoutingOverrideUpdateRequest's own
    # docstring on why that's what makes "omit = leave alone, null = clear"
    # PATCH semantics work here.
    updates = request.model_dump(exclude_unset=True)
    override = await repository.update(override, **updates)
    return _override_to_response(override)


@router.delete("/overrides/{override_id}", status_code=204)
async def delete_routing_override(
    override_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    repository = RoutingOverrideRepository(db)
    override = await repository.get_by_id(current_user.organization_id, override_id)
    if override is None:
        raise HTTPException(status_code=404, detail="Routing override not found.")
    await repository.delete(override)
