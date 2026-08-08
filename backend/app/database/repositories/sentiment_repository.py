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
    ) -> SentimentPredictionLog:
        record = SentimentPredictionLog(
            subject=subject,
            body=body,
            predicted_sentiment=sentiment,
            confidence=confidence,
            model_version=model_version,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
