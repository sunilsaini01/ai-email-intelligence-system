"""
Repository for spam prediction audit logs.

Why a repository class instead of calling `db.add()` directly from the
endpoint: the endpoint shouldn't know the storage shape (SQLAlchemy model
fields) — only "record this decision". That's what keeps the DB layer
swappable (e.g. this table's fields fold into `email_classifications` once
Module 1's ingestion pipeline exists) without touching API code.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.spam_prediction_log import SpamPredictionLog


class SpamPredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_prediction(
        self,
        subject: str,
        body: str,
        is_spam: bool,
        status: str,
        spam_score: float,
        confidence: float,
        threshold_used: float,
        model_version: str,
        processing_ms: float,
        organization_id: str | None = None,
    ) -> SpamPredictionLog:
        # organization_id optional (not required) so this repository's own
        # unit tests that don't pass it keep working unchanged -- the
        # model's own DEFAULT_ORGANIZATION_ID default still applies then.
        # Both real callers (the /spam/predict endpoint and, as of this
        # fix, the async SpamAgent) always pass the real one, derived from
        # the authenticated caller / the workflow's own organization_id --
        # never a value that could be spoofed.
        kwargs = {"organization_id": organization_id} if organization_id is not None else {}
        record = SpamPredictionLog(
            **kwargs,
            subject=subject,
            body=body,
            is_spam=is_spam,
            status=status,
            spam_score=spam_score,
            confidence=confidence,
            threshold_used=threshold_used,
            model_version=model_version,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
