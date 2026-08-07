"""
Repository for priority prediction audit logs. Same rationale as
spam_prediction_repository.py — the endpoint records a decision without
knowing the storage shape.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.priority_prediction_log import PriorityPredictionLog


class PriorityPredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_prediction(
        self,
        subject: str,
        body: str,
        priority: str,
        confidence: float,
        model_version: str,
        processing_ms: float,
    ) -> PriorityPredictionLog:
        record = PriorityPredictionLog(
            subject=subject,
            body=body,
            predicted_priority=priority,
            confidence=confidence,
            model_version=model_version,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
