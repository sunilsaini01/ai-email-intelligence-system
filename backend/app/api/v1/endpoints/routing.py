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

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.routing_decision_repository import RoutingDecisionRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.models.feedback_event import ACTION_CORRECTION
from app.schemas.routing import (
    RoutingFeedbackRequest,
    RoutingFeedbackResponse,
    RoutingPredictionRequest,
    RoutingPredictionResponse,
)
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_routing_feedback_logger
from app.services.routing_service import RoutingService, get_routing_service

router = APIRouter(prefix="/routing", tags=["Email Routing"])

logger = logging.getLogger("app.routing")


@router.post("/predict", response_model=RoutingPredictionResponse)
async def predict_routing(
    request: RoutingPredictionRequest,
    service: RoutingService = Depends(get_routing_service),
    db: AsyncSession = Depends(get_db),
) -> RoutingPredictionResponse:
    result = await run_in_threadpool(
        service.route,
        subject=request.subject,
        body=request.body,
        sender_email=request.sender_email,
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
