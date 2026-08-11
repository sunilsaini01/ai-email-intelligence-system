"""
Email summarization endpoints (Module 5 / Phase 6).

Structurally different from spam/priority/category's endpoints in one
respect: there is no `SummarizationServiceUnavailable` / 503 path.
Those three modules require a pre-trained artifact that might not exist
yet (fresh clone, training never run); summarization needs no such
artifact — extractive is pure algorithm (TF-IDF + PageRank, both computed
on the fly) and abstractive downloads its (pre-trained, not trained by
this codebase) weights on first use rather than depending on a local
training script having run. There is nothing to be "unavailable."

Otherwise mirrors the established pattern: run_in_threadpool for the sync
CPU-bound summarize() call, DB write bounded by
asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS) — see
docs/technical_debt/database_write_hang.md for this phase's investigation
into that timeout's real-world reliability, not repeated here.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.summary_repository import SummaryRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.models.feedback_event import ACTION_ACCEPT, ACTION_CORRECTION, ACTION_REJECT
from app.schemas.summarization import (
    SummarizationFeedbackRequest,
    SummarizationFeedbackResponse,
    SummarizationRequest,
    SummarizationResponse,
)
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_summarization_feedback_logger
from app.services.summarization_service import SummarizationService, get_summarization_service

router = APIRouter(prefix="/summarization", tags=["Email Summarization"])

logger = logging.getLogger("app.summarization")


@router.post("/predict", response_model=SummarizationResponse)
async def predict_summary(
    request: SummarizationRequest,
    service: SummarizationService = Depends(get_summarization_service),
    db: AsyncSession = Depends(get_db),
) -> SummarizationResponse:
    if request.summary_type == "abstractive":
        try:
            from app.nlp.abstractive_summarizer import get_abstractive_summarizer

            # MUST be threadpool-wrapped, not called directly: on a cold
            # process this triggers the ~115s first-load (model download +
            # deserialization, both blocking, synchronous work). Called
            # directly inside this async route body, that would block the
            # ENTIRE event loop for up to 115s -- not just this request,
            # every concurrent request this worker is serving (health
            # checks, spam/priority/category predictions, everything).
            # get_spam_service()/get_priority_service()/get_category_service()
            # don't need this same wrapping despite doing comparable
            # first-load work, because FastAPI's Depends() mechanism
            # automatically threadpools synchronous dependency callables --
            # this call sits inside the route body instead (conditional on
            # summary_type, so it doesn't fit a plain Depends()), which
            # does NOT get that automatic protection.
            await run_in_threadpool(get_abstractive_summarizer)
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Abstractive summarization model unavailable: {e}",
            ) from e

    result = await run_in_threadpool(
        service.summarize,
        subject=request.subject,
        body=request.body,
        messages=[m.model_dump() for m in request.messages] if request.messages else None,
        summary_type=request.summary_type,
        max_sentences=request.max_sentences,
    )

    logger.info(
        "summarization_prediction",
        extra={
            "summary_type": result["summary_type"],
            "skipped_short_input": result["skipped_short_input"],
            "input_word_count": result["input_word_count"],
            "entity_preservation_rate": result["entity_preservation_rate"],
            "model_version": result["model_version"],
            "processing_ms": result["processing_ms"],
        },
    )

    try:
        repository = SummaryRepository(db)
        await asyncio.wait_for(
            repository.log_summary(
                summary=result["summary"],
                summary_type=result["summary_type"],
                skipped_short_input=result["skipped_short_input"],
                input_word_count=result["input_word_count"],
                entity_preservation_rate=result["entity_preservation_rate"],
                model_version=result["model_version"],
                processing_ms=result["processing_ms"],
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("summarization_log_failed", exc_info=True)

    return SummarizationResponse(**result)


@router.post("/feedback", response_model=SummarizationFeedbackResponse)
async def submit_summary_feedback(
    request: SummarizationFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_summarization_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> SummarizationFeedbackResponse:
    feedback_id = feedback_logger.log_summary_feedback(
        original_text=request.original_text,
        generated_summary=request.generated_summary,
        accepted=request.accepted,
        corrected_summary=request.corrected_summary,
        quality_score=request.quality_score,
        reason=request.reason,
    )

    # A corrected_summary is a real CORRECTION regardless of `accepted`;
    # otherwise this is a plain accept/reject judgment, not a correction --
    # summarization has no confidence field at all (see
    # PHASE_11_AUDIT_REPORT.md finding), so it never contributes to the
    # confidence-bucketed correction rate, only the plain correction count.
    action = ACTION_CORRECTION if request.corrected_summary else (ACTION_ACCEPT if request.accepted else ACTION_REJECT)
    try:
        await record_feedback_event(
            db,
            module="summarization",
            action=action,
            original_value=request.generated_summary,
            corrected_value=request.corrected_summary,
            reviewer_id=request.reviewer_id,
            reason=request.reason,
        )
    except Exception:
        logger.warning("summarization_feedback_event_log_failed", exc_info=True)

    return SummarizationFeedbackResponse(status="logged", feedback_id=feedback_id)
