"""
GDPR controls (PRD SS6.4: "Right-to-deletion endpoint, configurable data
retention").

Right to deletion -- `erase_data_subject()`: every stored email FROM a
given sender address in the organization is hard-deleted, along with
everything derived from it that this system can link back to it:

  - the canonical `emails` row and its vector-store embedding;
  - per-module prediction audit rows (spam/priority/category/intent/
    sentiment/routing), matched on the exact (subject, body) the email
    had -- those tables predate a shared email id, so content is the only
    available join key -- plus sentiment rows matched on sender;
  - reply drafts generated for those emails, and notifications about them;
  - lines in the per-module feedback JSONL files with the same content.

Known, stated limits: `summary_logs` store only the generated summary
(no subject/body/sender), so a summary can't be attributed to a sender
and is removed by retention, not by subject erasure. `feedback_events`
rows hold labels, not email content, and are kept (PRD SS8.4: feedback is
retained indefinitely). MLflow model artifacts trained before the erasure
are not retrained by this call.

Retention -- `purge_expired_data()`: run daily by the agents process for
organizations that set `data_retention_days`; deletes content-bearing
rows older than the cutoff.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_prediction_log import CategoryPredictionLog
from app.models.email_record import EmailRecord
from app.models.intent_prediction_log import IntentPredictionLog
from app.models.notification import Notification
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.reply_draft import ReplyDraft
from app.models.routing_decision_log import RoutingDecisionLog
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.models.spam_prediction_log import SpamPredictionLog
from app.models.summary_log import SummaryLog
from app.services.feedback_service import feedback_log_dir

logger = logging.getLogger("app.privacy")


_CONTENT_LOG_MODELS = (
    SpamPredictionLog,
    PriorityPredictionLog,
    CategoryPredictionLog,
    IntentPredictionLog,
    SentimentPredictionLog,
    RoutingDecisionLog,
)


def _delete_vectors(records: list[EmailRecord]) -> int:
    """Best-effort: a vector-store outage must not leave the relational
    erasure half-done, so failures are logged and counted, not raised."""
    if not records:
        return 0
    from app.services.retrieval_service import get_retrieval_service

    service = get_retrieval_service()
    deleted = 0
    for record in records:
        try:
            service.delete_vector(content_hash=record.content_hash, organization_id=record.organization_id)
            deleted += 1
        except Exception:
            logger.warning("privacy_vector_delete_failed", exc_info=True, extra={"email_id": str(record.id)})
    return deleted


def scrub_feedback_files(contents: set[tuple[str, str]], artifact_dir: Path | None = None) -> int:
    artifact_dir = artifact_dir or feedback_log_dir()
    if not contents or not artifact_dir.exists():
        return 0
    removed = 0
    for path in artifact_dir.glob("*_feedback.jsonl"):
        kept = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if ((record.get("subject") or ""), (record.get("body") or "")) in contents:
                removed += 1
                continue
            kept.append(line)
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


async def erase_data_subject(
    session: AsyncSession, organization_id: str, sender_email: str, artifact_dir: Path | None = None
) -> dict:
    sender = sender_email.strip().lower()
    emails = list(
        (
            await session.execute(
                select(EmailRecord).where(
                    EmailRecord.organization_id == organization_id,
                    EmailRecord.sender_email.ilike(sender),
                )
            )
        ).scalars()
    )
    email_ids = [e.id for e in emails]
    contents = {(e.subject or "", e.body or "") for e in emails}
    counts: dict[str, int] = {"emails": len(emails)}

    counts["vectors"] = _delete_vectors(emails)

    for model in _CONTENT_LOG_MODELS:
        conditions = [and_(model.subject == subject, model.body == body) for subject, body in contents]
        if model is SentimentPredictionLog:
            conditions.append(SentimentPredictionLog.sender_email == sender)
        if not conditions:
            counts[model.__tablename__] = 0
            continue
        result = await session.execute(
            delete(model).where(model.organization_id == organization_id, or_(*conditions))
        )
        counts[model.__tablename__] = result.rowcount or 0

    draft_conditions = [and_(ReplyDraft.source_subject == s, ReplyDraft.source_body == b) for s, b in contents]
    if email_ids:
        draft_conditions.append(ReplyDraft.source_email_id.in_(email_ids))
    if draft_conditions:
        result = await session.execute(
            delete(ReplyDraft).where(ReplyDraft.organization_id == organization_id, or_(*draft_conditions))
        )
        counts["reply_drafts"] = result.rowcount or 0
    else:
        counts["reply_drafts"] = 0

    if email_ids:
        result = await session.execute(
            delete(Notification).where(
                Notification.organization_id == organization_id, Notification.email_id.in_(email_ids)
            )
        )
        counts["notifications"] = result.rowcount or 0
        await session.execute(delete(EmailRecord).where(EmailRecord.id.in_(email_ids)))
    else:
        counts["notifications"] = 0

    await session.commit()
    counts["feedback_file_lines"] = scrub_feedback_files(contents, artifact_dir)

    # Counts only -- never the address itself, which is the very data
    # being erased.
    logger.info("privacy_subject_erased", extra={"organization_id": organization_id, "counts": counts})
    return counts


async def purge_expired_data(session: AsyncSession, organization_id: str, retention_days: int) -> dict:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    expired_emails = list(
        (
            await session.execute(
                select(EmailRecord).where(
                    EmailRecord.organization_id == organization_id, EmailRecord.created_at < cutoff
                )
            )
        ).scalars()
    )
    counts: dict[str, int] = {"emails": len(expired_emails), "vectors": _delete_vectors(expired_emails)}
    if expired_emails:
        await session.execute(delete(EmailRecord).where(EmailRecord.id.in_([e.id for e in expired_emails])))

    for model in (*_CONTENT_LOG_MODELS, SummaryLog, ReplyDraft, Notification):
        result = await session.execute(
            delete(model).where(model.organization_id == organization_id, model.created_at < cutoff)
        )
        counts[model.__tablename__] = result.rowcount or 0

    await session.commit()
    logger.info(
        "privacy_retention_purge",
        extra={"organization_id": organization_id, "retention_days": retention_days, "counts": counts},
    )
    return counts
