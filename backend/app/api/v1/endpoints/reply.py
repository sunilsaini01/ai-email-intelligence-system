"""
Auto-Reply generation endpoints (Module 10 / Phase 10, FR-48 to FR-52).

Orchestration lives here, not in AutoReplyService, for the same reason
Phase 9's retrieval endpoint carries its own orchestration (see that
file's module docstring): this is a multi-system sequence (vector search
-> Postgres resolution-status filtering -> PII re-anonymization -> LLM
call -> Postgres persistence), not business logic that belongs bundled
into one service call.

FR-50 (10s) is enforced two ways: GroqProvider passes an 8s budget
directly to the SDK's own httpx-backed timeout (the real enforcement --
see app/inference/groq_provider.py's module docstring), and this endpoint
wraps generation in an outer `asyncio.wait_for` as a best-effort backstop
for retrieval+PII+LLM combined. Per RULE (see
docs/technical_debt/database_write_hang.md), `asyncio.wait_for` does not
perfectly bound a stuck underlying thread -- the SDK-level timeout is what
actually matters; the outer wrapper is defense in depth, not the primary
mechanism, and is disclosed as such rather than presented as an ironclad
guarantee.

A generated draft is ALWAYS persisted, even on failure (Step 8's
audit-trail requirement) -- `reply_drafts` is the canonical record of what
was attempted, same "not best-effort" stance Phase 9's `emails` table
already established for its own canonical record.
"""

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.email_repository import EmailRepository
from app.database.repositories.reply_draft_repository import ReplyDraftRepository
from app.database.session import DB_WRITE_TIMEOUT_SECONDS, get_db
from app.models.feedback_event import (
    ACTION_ACCEPT,
    ACTION_CORRECTION,
    ACTION_REJECT,
    ACTION_RELEVANCE,
)
from app.models.reply_draft import (
    POLICY_INSUFFICIENT_CONTEXT,
    POLICY_NO_SIMILAR_EMAILS,
    POLICY_TIMEOUT,
    STATUS_FAILED,
    STATUS_GENERATED,
    ReplyDraft,
)
from app.nlp.reply_prompt import RetrievedContextItem
from app.retrieval.resolution_status import RESOLVED
from app.schemas.auto_reply import (
    ReplyDraftResponse,
    ReplyEditRequest,
    ReplyFeedbackRequest,
    ReplyFeedbackResponse,
    ReplyGenerateRequest,
    ReplyReviewActionRequest,
)
from app.services.auto_reply_service import (
    MIN_CONTEXT_SCORE,
    AutoReplyService,
    GenerationOutcome,
    get_auto_reply_service,
    select_context,
)
from app.services.feedback_event_service import record_feedback_event
from app.services.feedback_service import FeedbackLogger, get_auto_reply_feedback_logger
from app.services.retrieval_service import RetrievalService, get_retrieval_service

router = APIRouter(prefix="/reply", tags=["Auto-Reply Generation"])
logger = logging.getLogger("app.auto_reply")

# HEURISTIC, same "overfetch generously, filter down" shape as
# retrieval.py's _OVERFETCH_MULTIPLIER/_OVERFETCH_CAP -- fetch more than
# needed because most candidates will be dropped by the RESOLVED filter
# (see docs/architecture_auto_reply.md "Resolved-Email Data Reality").
_CONTEXT_FETCH_K = 30

LLM_TIMEOUT_SECONDS = 8.0  # Section L latency budget -- passed straight to GroqProvider
TOTAL_LATENCY_BUDGET_SECONDS = 10.0  # FR-50, outer backstop only -- see module docstring


def _draft_to_response(draft: ReplyDraft) -> ReplyDraftResponse:
    return ReplyDraftResponse(
        draft_id=draft.id,
        status=draft.status,
        generation_policy=draft.generation_policy,
        generated_text=draft.generated_text,
        edited_text=draft.edited_text,
        edit_distance=draft.edit_distance,
        retrieved_context_count=draft.retrieved_context_count,
        retrieved_email_ids=[str(x) for x in (draft.retrieved_email_ids or [])],
        llm_provider=draft.llm_provider,
        llm_model=draft.llm_model,
        embedding_model=draft.embedding_model,
        retrieval_latency_ms=draft.retrieval_latency_ms,
        llm_latency_ms=draft.llm_latency_ms,
        total_latency_ms=draft.total_latency_ms,
        failure_reason=draft.failure_reason,
        created_at=draft.created_at,
        reviewed_at=draft.reviewed_at,
    )


def _log_review_action(draft: ReplyDraft, action: str) -> None:
    """Post-Phase-10 fix #2 -- Human Acceptance Rate tracking (FR-52).
    A per-action log line (draft_id/action/edit_distance/timestamp) is
    logged HERE, separately from the DB write already done in the
    repository, so this data is available two ways: aggregate directly
    from `reply_drafts` (status/edit_distance/reviewed_at columns, the
    durable source of truth), or from structured logs for anyone building
    a metrics pipeline off log aggregation instead of a DB query -- neither
    is a NEW mechanism, both reuse this module's existing persistence and
    logging conventions."""
    logger.info(
        "auto_reply_review_action",
        extra={
            "draft_id": str(draft.id),
            "action": action,
            "edit_distance": draft.edit_distance,
            "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else None,
        },
    )


async def _fetch_resolved_context(
    retrieval_service: RetrievalService,
    email_repository: EmailRepository,
    request: ReplyGenerateRequest,
) -> tuple[list[dict], str | None, float, bool]:
    """Returns (usable_candidates, embedding_model, retrieval_latency_ms,
    context_fetch_failed). Mirrors app/api/v1/endpoints/retrieval.py's own
    vector-search-then-DB-filter pattern, additionally filtering for
    resolution_status == RESOLVED (FR-48's literal requirement)."""
    start = time.perf_counter()
    try:
        raw = await run_in_threadpool(
            retrieval_service.search,
            subject=request.subject,
            body=request.body,
            top_k=_CONTEXT_FETCH_K,
            organization_id=request.organization_id,
            category=request.category,
            department=request.department,
        )
    except Exception:
        logger.error("auto_reply_retrieval_failed", exc_info=True)
        return [], None, round((time.perf_counter() - start) * 1000, 2), True

    candidates: list[dict] = []
    for match in raw["matches"]:
        record = await email_repository.get_by_content_hash(request.organization_id, match["content_hash"])
        if record is None or record.is_deleted or record.resolution_status != RESOLVED:
            continue
        candidates.append(
            {
                "score": match["score"],
                "email_id": str(record.id),
                "subject": record.subject,
                "body": record.body,
                "resolution_status": record.resolution_status,
            }
        )

    return candidates, raw["embedding_model"], round((time.perf_counter() - start) * 1000, 2), False


@router.post("/generate", response_model=ReplyDraftResponse)
async def generate_reply(
    request: ReplyGenerateRequest,
    auto_reply_service: AutoReplyService = Depends(get_auto_reply_service),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    db: AsyncSession = Depends(get_db),
) -> ReplyDraftResponse:
    start = time.perf_counter()

    candidates, embedding_model, retrieval_latency_ms, context_fetch_failed = await _fetch_resolved_context(
        retrieval_service, EmailRepository(db), request
    )
    selected = select_context(candidates, min_score=MIN_CONTEXT_SCORE)
    context_items = [
        RetrievedContextItem(
            email_id=c["email_id"], subject=c["subject"], body=c["body"], resolution_status=c["resolution_status"]
        )
        for c in selected
    ]

    try:
        outcome: GenerationOutcome = await asyncio.wait_for(
            run_in_threadpool(
                auto_reply_service.generate,
                request.subject,
                request.body,
                context_items,
                LLM_TIMEOUT_SECONDS,
            ),
            timeout=TOTAL_LATENCY_BUDGET_SECONDS,
        )
    except TimeoutError:
        logger.error("auto_reply_total_budget_exceeded")
        outcome = GenerationOutcome(generation_policy=POLICY_TIMEOUT, failure_reason="Total 10s latency budget exceeded.")

    # AutoReplyService.generate() cannot itself distinguish "retrieval found
    # nothing" (its own NO_SIMILAR_EMAILS default when given an empty list)
    # from "retrieval itself errored" -- only the endpoint knows that,
    # via context_fetch_failed. Override to the more specific, more honest
    # signal when it applies, but never overwrite a real TIMEOUT/LLM_FAILURE
    # the service already determined.
    if context_fetch_failed and outcome.generation_policy == POLICY_NO_SIMILAR_EMAILS:
        outcome.generation_policy = POLICY_INSUFFICIENT_CONTEXT
        outcome.failure_reason = outcome.failure_reason or "Retrieval failed; generation attempted without historical context."

    total_latency_ms = round((time.perf_counter() - start) * 1000, 2)
    repository = ReplyDraftRepository(db)

    try:
        draft = await asyncio.wait_for(
            repository.create(
                organization_id=request.organization_id,
                source_email_id=request.source_email_id,
                source_subject=request.subject,
                source_body=request.body,
                retrieved_email_ids=[c["email_id"] for c in selected],
                retrieved_context_count=len(selected),
                generated_text=outcome.generated_text,
                status=STATUS_GENERATED if outcome.generated_text is not None else STATUS_FAILED,
                generation_policy=outcome.generation_policy,
                failure_reason=outcome.failure_reason,
                llm_provider=outcome.llm_provider,
                llm_model=outcome.llm_model,
                embedding_model=embedding_model,
                retrieval_latency_ms=retrieval_latency_ms,
                llm_latency_ms=outcome.llm_latency_ms,
                total_latency_ms=total_latency_ms,
            ),
            timeout=DB_WRITE_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logger.error("auto_reply_draft_persist_failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Could not persist the reply draft.") from e

    logger.info(
        "auto_reply_generate",
        extra={
            "draft_id": str(draft.id),
            "generation_policy": draft.generation_policy,
            "status": draft.status,
            "retrieved_context_count": draft.retrieved_context_count,
            "total_latency_ms": total_latency_ms,
        },
    )
    return _draft_to_response(draft)


@router.get("/{draft_id}", response_model=ReplyDraftResponse)
async def get_reply_draft(
    draft_id: uuid.UUID, organization_id: str = "default", db: AsyncSession = Depends(get_db)
) -> ReplyDraftResponse:
    draft = await ReplyDraftRepository(db).get_by_id(organization_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Reply draft not found.")
    return _draft_to_response(draft)


@router.post("/{draft_id}/approve", response_model=ReplyDraftResponse)
async def approve_reply_draft(
    draft_id: uuid.UUID,
    request: ReplyReviewActionRequest,
    organization_id: str = "default",
    db: AsyncSession = Depends(get_db),
) -> ReplyDraftResponse:
    repository = ReplyDraftRepository(db)
    draft = await repository.get_by_id(organization_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Reply draft not found.")
    draft = await repository.approve(draft, reviewer_id=request.reviewer_id)

    _log_review_action(draft, action="approved")
    try:
        await record_feedback_event(
            db,
            module="auto_reply",
            action=ACTION_ACCEPT,
            organization_id=organization_id,
            prediction_id=draft.id,
            original_value=draft.generated_text,
            reviewer_id=draft.reviewer_id,
        )
    except Exception:
        logger.warning("auto_reply_approve_feedback_event_log_failed", exc_info=True)

    # Post-Phase-10 fix #3 -- approving a draft is the closest signal this
    # codebase has to "this case was resolved" (there is no send step to
    # hook -- FR-49 means one never exists, see docs/security_auto_reply.md
    # "Never Auto-Send"). Best-effort, non-fatal: the approve action itself
    # must still succeed even if this side effect fails (e.g. the source
    # email was never indexed as a canonical EmailRecord -- source_email_id
    # is None -- or was soft-deleted since). Closes, over time, the gap
    # docs/architecture_auto_reply.md "Resolved-Email Data Reality" flagged:
    # Phase 9's resolution_status never auto-transitioned anywhere before this.
    if draft.source_email_id is not None:
        try:
            updated = await EmailRepository(db).update_resolution_status(
                organization_id, draft.source_email_id, RESOLVED
            )
            if updated is not None:
                logger.info(
                    "auto_reply_source_email_auto_resolved",
                    extra={"draft_id": str(draft.id), "email_id": str(draft.source_email_id)},
                )
        except Exception:
            logger.warning("auto_reply_auto_resolve_failed", exc_info=True, extra={"draft_id": str(draft.id)})

    return _draft_to_response(draft)


@router.post("/{draft_id}/edit", response_model=ReplyDraftResponse)
async def edit_reply_draft(
    draft_id: uuid.UUID,
    request: ReplyEditRequest,
    organization_id: str = "default",
    db: AsyncSession = Depends(get_db),
) -> ReplyDraftResponse:
    repository = ReplyDraftRepository(db)
    draft = await repository.get_by_id(organization_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Reply draft not found.")
    original_text = draft.generated_text
    draft = await repository.edit(draft, edited_text=request.edited_text, reviewer_id=request.reviewer_id)

    _log_review_action(draft, action="edited")
    try:
        await record_feedback_event(
            db,
            module="auto_reply",
            action=ACTION_CORRECTION,
            organization_id=organization_id,
            prediction_id=draft.id,
            original_value=original_text,
            corrected_value=draft.edited_text,
            reviewer_id=draft.reviewer_id,
        )
    except Exception:
        logger.warning("auto_reply_edit_feedback_event_log_failed", exc_info=True)

    return _draft_to_response(draft)


@router.post("/{draft_id}/reject", response_model=ReplyDraftResponse)
async def reject_reply_draft(
    draft_id: uuid.UUID,
    request: ReplyReviewActionRequest,
    organization_id: str = "default",
    db: AsyncSession = Depends(get_db),
) -> ReplyDraftResponse:
    repository = ReplyDraftRepository(db)
    draft = await repository.get_by_id(organization_id, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Reply draft not found.")
    draft = await repository.reject(draft, reviewer_id=request.reviewer_id)

    _log_review_action(draft, action="rejected")
    try:
        await record_feedback_event(
            db,
            module="auto_reply",
            action=ACTION_REJECT,
            organization_id=organization_id,
            prediction_id=draft.id,
            original_value=draft.generated_text,
            reviewer_id=draft.reviewer_id,
        )
    except Exception:
        logger.warning("auto_reply_reject_feedback_event_log_failed", exc_info=True)

    return _draft_to_response(draft)


@router.post("/feedback", response_model=ReplyFeedbackResponse)
async def submit_reply_feedback(
    request: ReplyFeedbackRequest,
    feedback_logger: FeedbackLogger = Depends(get_auto_reply_feedback_logger),
    db: AsyncSession = Depends(get_db),
) -> ReplyFeedbackResponse:
    feedback_id = feedback_logger.log_auto_reply_feedback(
        draft_id=str(request.draft_id), useful=request.useful, comment=request.comment
    )

    try:
        await record_feedback_event(
            db,
            module="auto_reply",
            action=ACTION_RELEVANCE,
            prediction_id=request.draft_id,  # references reply_drafts.id
            corrected_value={"useful": request.useful},
            reviewer_id=request.reviewer_id,
            reason=request.comment,
        )
    except Exception:
        logger.warning("auto_reply_feedback_event_log_failed", exc_info=True)

    return ReplyFeedbackResponse(status="logged", feedback_id=feedback_id)
