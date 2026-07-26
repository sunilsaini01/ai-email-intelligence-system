"""
Spam classification endpoints (Module 2 / Phase 3).

Why classification failures return 503, not 500:
    A missing model artifact is an operational state ("training hasn't run
    yet / model wasn't deployed"), not a bug in the request. 503 tells the
    caller and any monitoring to treat this as "service not ready", the
    same signal /health/ready uses for a down database.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.spam import (
    SpamFeedbackRequest,
    SpamFeedbackResponse,
    SpamPredictionRequest,
    SpamPredictionResponse,
)
from app.services.feedback_service import FeedbackLogger, get_feedback_logger
from app.services.spam_service import SpamService, SpamServiceUnavailable, get_spam_service

router = APIRouter(prefix="/spam", tags=["Spam Detection"])


def _get_spam_service() -> SpamService:
    try:
        return get_spam_service()
    except SpamServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/predict", response_model=SpamPredictionResponse)
def predict_spam(
    request: SpamPredictionRequest,
    service: SpamService = Depends(_get_spam_service),
) -> SpamPredictionResponse:
    result = service.classify(subject=request.subject, body=request.body)
    return SpamPredictionResponse(**result)


@router.post("/feedback", response_model=SpamFeedbackResponse)
def submit_spam_feedback(
    request: SpamFeedbackRequest,
    logger: FeedbackLogger = Depends(get_feedback_logger),
) -> SpamFeedbackResponse:
    feedback_id = logger.log_correction(
        subject=request.subject,
        body=request.body,
        predicted_label=request.predicted_label,
        corrected_label=request.corrected_label,
        comment=request.comment,
    )
    return SpamFeedbackResponse(status="logged", feedback_id=feedback_id)
