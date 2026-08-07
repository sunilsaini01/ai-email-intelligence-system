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
    ) -> SpamPredictionLog:
        record = SpamPredictionLog(
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
