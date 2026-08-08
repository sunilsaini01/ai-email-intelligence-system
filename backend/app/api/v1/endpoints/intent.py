"""
Intent detection endpoints (Module 7 / Phase 7B).

Mirrors category.py's structure (503 on missing artifact, run_in_threadpool,
bounded DB write) -- IntentService DOES have an artifact dependency, unlike
Sentiment, since the served model is a trained classifier (see
docs/data_audit_intent.md §4), not a zero-shot scorer. FR-33's SYNTHETIC
warning (docs/data_audit_intent.md) applies to every prediction this
endpoint returns until intent_baseline.joblib is retrained on real annotated
data.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.intent_prediction_repository import IntentPredictionRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.schemas.intent import (
    IntentFeedbackRequest,
    IntentFeedbackResponse,
    IntentPredictionRequest,
    IntentPredictionResponse,
)
from app.services.feedback_service import FeedbackLogger, get_intent_feedback_logger
from app.services.intent_service import (
    IntentService,
    IntentServiceUnavailable,
    get_intent_service,
)

router = APIRouter(prefix="/intent", tags=["Intent Detection"])

logger = logging.getLogger("app.intent")


def _get_intent_service() -> IntentService:
    try:
        return get_intent_service()
    except IntentServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/predict", response_model=IntentPredictionResponse)
async def predict_intent(
    request: IntentPredictionRequest,
    service: IntentService = Depends(_get_intent_service),
    db: AsyncSession = Depends(get_db),
) -> IntentPredictionResponse:
    result = await run_in_threadpool(
        service.analyze,
        subject=request.subject,
        body=request.body,
    )

    logger.info(
        "intent_prediction",
        extra={
            "intents": [i["intent"] for i in result["intents"]],
            "model_version": result["model_version"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = IntentPredictionRepository(db)
        await asyncio.wait_for(
            repository.log_prediction(
                subject=request.subject,
                body=request.body,
                intents=[i["intent"] for i in result["intents"]],
                confidences={i["intent"]: i["confidence"] for i in result["intents"]},
                entities=result["entities"],
                model_version=result["model_version"],
                processing_ms=result["processing_ms"],
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("intent_prediction_log_failed", exc_info=True)

    return IntentPredictionResponse(**result)


@router.post("/feedback", response_model=IntentFeedbackResponse)
def submit_intent_feedback(
    request: IntentFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_intent_feedback_logger),
) -> IntentFeedbackResponse:
    feedback_id = feedback_logger.log_correction(
        subject=request.subject,
        body=request.body,
        predicted_label=request.predicted_label,
        corrected_label=request.corrected_label,
        comment=request.comment,
    )
    return IntentFeedbackResponse(status="logged", feedback_id=feedback_id)
