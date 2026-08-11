"""
Similar-email retrieval endpoints (Module 9 / Phase 9, FR-43 to FR-47).

Deviates from every prior module's endpoint shape in one deliberate way:
Postgres writes here are NOT best-effort/non-blocking (unlike every other
module's `try: await asyncio.wait_for(repository.log_...) except Exception:
logger.warning(...)` pattern). Every prior module's DB write is an AUDIT
LOG of a decision already made and already returned to the caller --
losing it is unfortunate but doesn't corrupt anything. Here, the `emails`
row IS the canonical record (Step 2) -- if it fails to write, there is no
"decision" to return at all, so failures propagate as real HTTP errors
instead of being swallowed. Vector-store failures are also NOT masked as
empty results (RULE 9) -- see `_index_email`/`_search_candidates` below.

Index/search are each a short DB -> service -> DB sequence (see
app/services/retrieval_service.py's module docstring for why), so this
file carries more orchestration than a typical `*/predict` endpoint;
that's the multi-system nature of retrieval (Postgres + vector store),
not business logic that belongs in a service.
"""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.email_repository import EmailRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.models.feedback_event import ACTION_RELEVANCE
from app.retrieval.identity import compute_content_hash
from app.retrieval.resolution_status import RESOLUTION_STATUSES
from app.schemas.retrieval import (
    ResolutionStatusUpdateRequest,
    ResolutionStatusUpdateResponse,
    RetrievalFeedbackRequest,
    RetrievalFeedbackResponse,
    RetrievalIndexRequest,
    RetrievalIndexResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    SimilarEmailMatch,
)
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_retrieval_feedback_logger
from app.services.retrieval_service import RetrievalService, get_retrieval_service

router = APIRouter(prefix="/retrieval", tags=["Similar Email Retrieval"])
logger = logging.getLogger("app.retrieval")

# How many extra vector-store candidates to fetch beyond top_k so that
# post-query DB filtering (resolution_status, is_deleted -- see
# retrieval_service.py's module docstring for why those aren't in the
# vector store's own `where`) rarely under-fills the final result set.
# HEURISTIC, not derived from any measured selectivity -- see
# docs/vector_index_consistency.md.
_OVERFETCH_MULTIPLIER = 4
_OVERFETCH_CAP = 50


@router.post("/index", response_model=RetrievalIndexResponse)
async def index_email(
    request: RetrievalIndexRequest,
    service: RetrievalService = Depends(get_retrieval_service),
    db: AsyncSession = Depends(get_db),
) -> RetrievalIndexResponse:
    start = time.perf_counter()
    content_hash = compute_content_hash(request.subject, request.body)
    repository = EmailRepository(db)

    try:
        record, was_created = await asyncio.wait_for(
            repository.upsert_by_content_hash(
                organization_id=request.organization_id,
                content_hash=content_hash,
                subject=request.subject,
                body=request.body,
                sender_email=request.sender_email,
                received_at=request.received_at or datetime.now(UTC),
                category=request.category,
                department=request.department,
                priority=request.priority,
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.error("retrieval_index_db_write_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Could not persist the canonical email record.") from e

    try:
        result = await run_in_threadpool(
            service.index_email,
            content_hash=content_hash,
            subject=request.subject,
            body=request.body,
            category=request.category,
            department=request.department,
            organization_id=request.organization_id,
        )
    except Exception as e:
        logger.error("retrieval_index_embedding_failed", exc_info=True)
        await repository.mark_failed(record)
        raise HTTPException(
            status_code=503, detail="Embedding/vector-store unavailable; email persisted but not indexed."
        ) from e

    record = await repository.mark_indexed(
        record,
        embedding_model=result["embedding_model"],
        embedding_version=result["collection"],
        vector_collection=result["collection"],
    )

    logger.info(
        "retrieval_index",
        extra={
            "email_id": str(record.id),
            "was_created": was_created,
            "index_status": record.index_status,
            "embedding_model": result["embedding_model"],
            "pii_entity_types_found": result["pii_entity_types_found"],
        },
    )

    return RetrievalIndexResponse(
        email_id=record.id,
        content_hash=content_hash,
        was_created=was_created,
        index_status=record.index_status,
        embedding_model=result["embedding_model"],
        embedding_dimension=result["embedding_dimension"],
        pii_entity_types_found=result["pii_entity_types_found"],
        processing_ms=round((time.perf_counter() - start) * 1000, 2),
    )


@router.post("/search", response_model=RetrievalSearchResponse)
async def search_similar_emails(
    request: RetrievalSearchRequest,
    service: RetrievalService = Depends(get_retrieval_service),
    db: AsyncSession = Depends(get_db),
) -> RetrievalSearchResponse:
    start = time.perf_counter()
    fetch_k = min(request.top_k * _OVERFETCH_MULTIPLIER, _OVERFETCH_CAP)

    try:
        raw = await run_in_threadpool(
            service.search,
            subject=request.subject,
            body=request.body,
            top_k=fetch_k,
            organization_id=request.organization_id,
            category=request.category,
            department=request.department,
        )
    except Exception as e:
        # RULE 9 -- never silently return zero results when the vector
        # store actually failed.
        logger.error("retrieval_search_vector_store_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Vector store unavailable.") from e

    repository = EmailRepository(db)
    results: list[SimilarEmailMatch] = []
    for match in raw["matches"]:
        if len(results) >= request.top_k:
            break
        record = await repository.get_by_content_hash(request.organization_id, match["content_hash"])
        if record is None or record.is_deleted:
            continue  # Step 12 point 8/9 -- stale vector-store entry, skip rather than error
        if request.resolution_status and record.resolution_status != request.resolution_status:
            continue
        results.append(
            SimilarEmailMatch(
                email_id=record.id,
                score=match["score"],
                subject=record.subject,
                category=record.category,
                department=record.department,
                resolution_status=record.resolution_status,
                received_at=record.received_at,
            )
        )

    logger.info(
        "retrieval_search",
        extra={
            "result_count": len(results),
            "requested_top_k": request.top_k,
            "embedding_model": raw["embedding_model"],
        },
    )

    return RetrievalSearchResponse(
        query_id=uuid.uuid4(),
        results=results,
        embedding_model=raw["embedding_model"],
        result_count=len(results),
        processing_ms=round((time.perf_counter() - start) * 1000, 2),
    )


def _parse_email_id(email_id: str) -> uuid.UUID:
    """Validated at the API boundary, not left to whatever the DB driver
    happens to do with a malformed string. Deliberately NOT relying on
    "the query raises an exception" for this: SQLite (used in this
    project's tests) compares EmailRecord.id to an arbitrary string
    without raising at all -- it just matches no rows -- while Postgres's
    native UUID column WOULD raise on invalid input. Validating explicitly
    here means both backends return the same 422, not a
    backend-dependent 404-vs-422 split."""
    try:
        return uuid.UUID(email_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Malformed email_id -- must be a UUID.") from e


@router.patch("/emails/{email_id}/resolution", response_model=ResolutionStatusUpdateResponse)
async def update_resolution_status(
    email_id: str,
    request: ResolutionStatusUpdateRequest,
    organization_id: str = "default",
    db: AsyncSession = Depends(get_db),
) -> ResolutionStatusUpdateResponse:
    if request.resolution_status not in RESOLUTION_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"resolution_status must be one of {RESOLUTION_STATUSES}"
        )

    parsed_id = _parse_email_id(email_id)
    repository = EmailRepository(db)
    record = await repository.update_resolution_status(organization_id, parsed_id, request.resolution_status)

    if record is None:
        raise HTTPException(status_code=404, detail="Email not found.")

    return ResolutionStatusUpdateResponse(email_id=record.id, resolution_status=record.resolution_status)


@router.delete("/emails/{email_id}", status_code=204)
async def delete_email(
    email_id: str,
    organization_id: str = "default",
    service: RetrievalService = Depends(get_retrieval_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    parsed_id = _parse_email_id(email_id)
    repository = EmailRepository(db)
    record = await repository.soft_delete(organization_id, parsed_id)

    if record is None:
        raise HTTPException(status_code=404, detail="Email not found.")

    # Immediate, not lazy (Step 20) -- a soft-deleted email's vector must
    # never appear in a search result, so it's removed from the vector
    # store right away rather than relying only on the is_deleted filter
    # applied in search_similar_emails above.
    await run_in_threadpool(service.delete_vector, content_hash=record.content_hash, organization_id=organization_id)


@router.post("/feedback", response_model=RetrievalFeedbackResponse)
async def submit_retrieval_feedback(
    request: RetrievalFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_retrieval_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> RetrievalFeedbackResponse:
    feedback_id = feedback_logger.log_retrieval_feedback(
        query_subject=request.query_subject,
        query_body=request.query_body,
        result_email_id=str(request.result_email_id) if request.result_email_id else None,
        useful=request.useful,
        comment=request.comment,
    )

    try:
        await record_feedback_event(
            db,
            module="retrieval",
            action=ACTION_RELEVANCE,
            prediction_id=request.result_email_id,  # references emails.id, not a *_prediction_logs row
            corrected_value={"useful": request.useful},
            reviewer_id=request.reviewer_id,
            reason=request.comment,
        )
    except Exception:
        logger.warning("retrieval_feedback_event_log_failed", exc_info=True)

    return RetrievalFeedbackResponse(status="logged", feedback_id=feedback_id)
