"""
Spam classification endpoints (Module 2 / Phase 3-4).

Why classification failures return 503, not 500:
    A missing model artifact is an operational state ("training hasn't run
    yet / model wasn't deployed"), not a bug in the request. 503 tells the
    caller and any monitoring to treat this as "service not ready", the
    same signal /health/ready uses for a down database.

Why a failed DB write does not fail the request:
    Persisting the audit log is an observability concern, not the reason the
    caller made the request. If the DB is down, the caller still needs their
    spam/ham answer — losing one audit row is recoverable (or, later,
    replayable from a queue); silently blocking every prediction on DB health
    is not. The failure is still logged loudly so it's visible to monitoring.

Why the DB write is wrapped in asyncio.wait_for, not just try/except:
    try/except alone only protects against a *raised* exception (e.g. auth
    failure, which fails fast). It does nothing for a *hanging* connection
    attempt — observed in practice against a local Postgres with an
    apparent IPv6 routing issue, where the request hung 75+ seconds instead
    of failing. DB_WRITE_TIMEOUT_SECONDS (app/database/session.py) bounds
    the worst case explicitly instead of trusting the DB driver to always
    fail fast.

Why service.classify() runs via run_in_threadpool, not a direct call:
    This route must be `async def` to `await` the DB write below. But
    `classify()` is synchronous, CPU-bound work (TF-IDF vectorization + spaCy
    lemmatization) — calling it directly would block the single event loop
    thread for the duration of every prediction, serializing all concurrent
    requests behind each other. A plain `def` route gets this for free (FastAPI
    runs sync path functions in a threadpool automatically); an `async def`
    route does not extend that courtesy to sync calls made inside it. This
    is the "async def route calling blocking code" anti-pattern the
    database/session.py docstring already warns about for DB calls — the
    exact same failure mode, here for CPU work instead of I/O.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.spam_prediction_repository import SpamPredictionRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.schemas.spam import (
    SpamFeedbackRequest,
    SpamFeedbackResponse,
    SpamPredictionRequest,
    SpamPredictionResponse,
)
from app.services.feedback_service import FeedbackLogger, get_feedback_logger
from app.services.spam_service import SpamService, SpamServiceUnavailable, get_spam_service

router = APIRouter(prefix="/spam", tags=["Spam Detection"])

logger = logging.getLogger("app.spam")


def _get_spam_service() -> SpamService:
    try:
        return get_spam_service()
    except SpamServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/predict", response_model=SpamPredictionResponse)
async def predict_spam(
    request: SpamPredictionRequest,
    service: SpamService = Depends(_get_spam_service),
    db: AsyncSession = Depends(get_db),
) -> SpamPredictionResponse:
    result = await run_in_threadpool(service.classify, subject=request.subject, body=request.body)

    # Structured, prediction-level observability — deliberately NOT logging
    # subject/body (see app/core/logging.py's own warning against logging
    # raw content at INFO level).
    logger.info(
        "spam_prediction",
        extra={
            "is_spam": result["is_spam"],
            "status": result["status"],
            "spam_score": result["spam_score"],
            "confidence": result["confidence"],
            "model_version": result["model_version"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = SpamPredictionRepository(db)
        await asyncio.wait_for(
            repository.log_prediction(
                subject=request.subject,
                body=request.body,
                **result,
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("spam_prediction_log_failed", exc_info=True)

    return SpamPredictionResponse(**result)


@router.post("/feedback", response_model=SpamFeedbackResponse)
def submit_spam_feedback(
    request: SpamFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_feedback_logger),
) -> SpamFeedbackResponse:
    feedback_id = feedback_logger.log_correction(
        subject=request.subject,
        body=request.body,
        predicted_label=request.predicted_label,
        corrected_label=request.corrected_label,
        comment=request.comment,
    )
    return SpamFeedbackResponse(status="logged", feedback_id=feedback_id)
