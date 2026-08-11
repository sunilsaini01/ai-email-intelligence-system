"""
Email categorization endpoints (Module 4 / Phase 5).

Mirrors app/api/v1/endpoints/priority.py's structure and its load-bearing
decisions (503 not 500 on missing artifact, run_in_threadpool for the sync
CPU-bound classify() call, DB write bounded by
asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS)) — see that file's docstring for
the full reasoning, not repeated here since it's identical.

Model-specific to categorization: docs/data_audit_categorization.md's
SYNTHETIC warning applies to every prediction this endpoint returns until
category_baseline.joblib is retrained on real annotated data (see
docs/annotation_guidelines_categorization.md for what that requires).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.category_prediction_repository import CategoryPredictionRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.models.feedback_event import ACTION_CORRECTION
from app.schemas.category import (
    CategoryFeedbackRequest,
    CategoryFeedbackResponse,
    CategoryPredictionRequest,
    CategoryPredictionResponse,
)
from app.services.category_service import (
    CategoryService,
    CategoryServiceUnavailable,
    get_category_service,
)
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_category_feedback_logger

router = APIRouter(prefix="/categorization", tags=["Email Categorization"])

logger = logging.getLogger("app.categorization")


def _get_category_service() -> CategoryService:
    try:
        return get_category_service()
    except CategoryServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/predict", response_model=CategoryPredictionResponse)
async def predict_category(
    request: CategoryPredictionRequest,
    service: CategoryService = Depends(_get_category_service),
    db: AsyncSession = Depends(get_db),
) -> CategoryPredictionResponse:
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

    categories = [c["category"] for c in result["categories"]]
    confidences = {c["category"]: c["confidence"] for c in result["categories"]}

    logger.info(
        "category_prediction",
        extra={
            "categories": categories,
            "model_version": result["model_version"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = CategoryPredictionRepository(db)
        await asyncio.wait_for(
            repository.log_prediction(
                subject=request.subject,
                body=request.body,
                categories=categories,
                confidences=confidences,
                model_version=result["model_version"],
                processing_ms=result["processing_ms"],
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("category_prediction_log_failed", exc_info=True)

    return CategoryPredictionResponse(**result)


@router.post("/feedback", response_model=CategoryFeedbackResponse)
async def submit_category_feedback(
    request: CategoryFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_category_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> CategoryFeedbackResponse:
    feedback_id = feedback_logger.log_correction(
        subject=request.subject,
        body=request.body,
        predicted_label=request.predicted_categories,
        corrected_label=request.corrected_categories,
        comment=request.comment,
    )

    try:
        await record_feedback_event(
            db,
            module="category",
            action=ACTION_CORRECTION,
            original_value=request.predicted_categories,
            corrected_value=request.corrected_categories,
            reviewer_id=request.reviewer_id,
            reason=request.comment,
        )
    except Exception:
        logger.warning("category_feedback_event_log_failed", exc_info=True)

    return CategoryFeedbackResponse(status="logged", feedback_id=feedback_id)
