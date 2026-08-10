"""
Sentiment analysis endpoints (Module 6 / Phase 7A).

Mirrors priority.py's structure with one deliberate omission: no 503 /
`*ServiceUnavailable` path -- see app/services/sentiment_service.py's
docstring for why (no trained artifact for a "hasn't been trained yet"
state to guard against, same reasoning as summarization.py).

Otherwise identical to every other module's endpoint: run_in_threadpool for
the sync predict call, DB write bounded by
asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS), non-fatal logging on write
failure. FR-29's SYNTHETIC/PROVISIONAL data-status warning applies to every
prediction this endpoint returns -- see docs/data_audit_sentiment.md.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.sentiment_repository import SentimentPredictionRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.schemas.sentiment import (
    SentimentFeedbackRequest,
    SentimentFeedbackResponse,
    SentimentPredictionRequest,
    SentimentPredictionResponse,
)
from app.models.feedback_event import ACTION_CORRECTION
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_sentiment_feedback_logger
from app.services.sentiment_service import SentimentService, get_sentiment_service

router = APIRouter(prefix="/sentiment", tags=["Sentiment Analysis"])

logger = logging.getLogger("app.sentiment")


@router.post("/predict", response_model=SentimentPredictionResponse)
async def predict_sentiment(
    request: SentimentPredictionRequest,
    service: SentimentService = Depends(get_sentiment_service),
    db: AsyncSession = Depends(get_db),
) -> SentimentPredictionResponse:
    result = await run_in_threadpool(
        service.analyze,
        subject=request.subject,
        body=request.body,
    )

    logger.info(
        "sentiment_prediction",
        extra={
            "sentiment": result["sentiment"],
            "confidence": result["confidence"],
            "model_version": result["model_version"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = SentimentPredictionRepository(db)
        await asyncio.wait_for(
            repository.log_prediction(
                subject=request.subject,
                body=request.body,
                sentiment=result["sentiment"],
                confidence=result["confidence"],
                model_version=result["model_version"],
                processing_ms=result["processing_ms"],
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("sentiment_prediction_log_failed", exc_info=True)

    return SentimentPredictionResponse(**result)


@router.post("/feedback", response_model=SentimentFeedbackResponse)
async def submit_sentiment_feedback(
    request: SentimentFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_sentiment_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> SentimentFeedbackResponse:
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
            module="sentiment",
            action=ACTION_CORRECTION,
            original_value=request.predicted_label,
            corrected_value=request.corrected_label,
            reviewer_id=request.reviewer_id,
            reason=request.comment,
        )
    except Exception:
        logger.warning("sentiment_feedback_event_log_failed", exc_info=True)

    return SentimentFeedbackResponse(status="logged", feedback_id=feedback_id)
