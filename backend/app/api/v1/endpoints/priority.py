"""
Priority classification endpoints (Module 3 / Phase 4).

Mirrors app/api/v1/endpoints/spam.py's structure and its load-bearing
decisions (503 not 500 on missing artifact, run_in_threadpool for the sync
CPU-bound classify() call, and the DB write bounded by
asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS) so a hanging connection attempt
can't block the response indefinitely — see that file's docstring for the
full reasoning, not repeated here since it's identical).

Model-specific to priority: docs/data_audit_priority.md's SYNTHETIC warning
applies to every prediction this endpoint returns until priority_baseline.joblib
is retrained on real annotated data.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.priority_prediction_repository import PriorityPredictionRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.schemas.priority import (
    PriorityFeedbackRequest,
    PriorityFeedbackResponse,
    PriorityPredictionRequest,
    PriorityPredictionResponse,
)
from app.models.feedback_event import ACTION_CORRECTION
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_priority_feedback_logger
from app.services.priority_service import (
    PriorityService,
    PriorityServiceUnavailable,
    get_priority_service,
)

router = APIRouter(prefix="/priority", tags=["Priority Classification"])

logger = logging.getLogger("app.priority")


def _get_priority_service() -> PriorityService:
    try:
        return get_priority_service()
    except PriorityServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/predict", response_model=PriorityPredictionResponse)
async def predict_priority(
    request: PriorityPredictionRequest,
    service: PriorityService = Depends(_get_priority_service),
    db: AsyncSession = Depends(get_db),
) -> PriorityPredictionResponse:
    result = await run_in_threadpool(
        service.classify,
        subject=request.subject,
        body=request.body,
        sender_email=request.sender_email,
        received_at=request.received_at,
        recipient_to=request.recipient_to,
        recipient_cc=request.recipient_cc,
        is_reply=request.is_reply,
        is_forward=request.is_forward,
        has_attachments=request.has_attachments,
        attachment_count=request.attachment_count,
    )

    logger.info(
        "priority_prediction",
        extra={
            "priority": result["priority"],
            "confidence": result["confidence"],
            "model_version": result["model_version"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = PriorityPredictionRepository(db)
        await asyncio.wait_for(
            repository.log_prediction(
                subject=request.subject,
                body=request.body,
                priority=result["priority"],
                confidence=result["confidence"],
                model_version=result["model_version"],
                processing_ms=result["processing_ms"],
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("priority_prediction_log_failed", exc_info=True)

    return PriorityPredictionResponse(**result)


@router.post("/feedback", response_model=PriorityFeedbackResponse)
async def submit_priority_feedback(
    request: PriorityFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_priority_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> PriorityFeedbackResponse:
    feedback_id = feedback_logger.log_correction(
        subject=request.subject,
        body=request.body,
        predicted_label=request.predicted_label,
        corrected_label=request.corrected_label,
        comment=request.comment,
    )

    try:
        await record_feedback_event(
            db,
            module="priority",
            action=ACTION_CORRECTION,
            original_value=request.predicted_label,
            corrected_value=request.corrected_label,
            reviewer_id=request.reviewer_id,
            reason=request.comment,
        )
    except Exception:
        logger.warning("priority_feedback_event_log_failed", exc_info=True)

    return PriorityFeedbackResponse(status="logged", feedback_id=feedback_id)
