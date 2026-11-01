"""
Repository for sentiment prediction audit logs. Same rationale as
priority_prediction_repository.py -- the endpoint records a decision
without knowing the storage shape.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sentiment_prediction_log import SentimentPredictionLog


class SentimentPredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_prediction(
        self,
        subject: str,
        body: str,
        sentiment: str,
        confidence: float,
        model_version: str,
        processing_ms: float,
        organization_id: str | None = None,
        sender_email: str | None = None,
        primary_emotion: str | None = None,
        emotions: list | None = None,
    ) -> SentimentPredictionLog:
        # organization_id optional -- see spam_prediction_repository.py's
        # identical parameter for the full rationale.
        kwargs = {"organization_id": organization_id} if organization_id is not None else {}
        record = SentimentPredictionLog(
            **kwargs,
            subject=subject,
            body=body,
            predicted_sentiment=sentiment,
            confidence=confidence,
            model_version=model_version,
            processing_ms=processing_ms,
            sender_email=(sender_email or "").strip().lower() or None,
            primary_emotion=primary_emotion,
            emotions=emotions,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
