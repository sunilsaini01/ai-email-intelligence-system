"""
Repository for intent prediction audit logs. Same rationale as
category_prediction_repository.py.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intent_prediction_log import IntentPredictionLog


class IntentPredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_prediction(
        self,
        subject: str,
        body: str,
        intents: list[str],
        confidences: dict[str, float],
        entities: dict,
        model_version: str,
        processing_ms: float,
    ) -> IntentPredictionLog:
        record = IntentPredictionLog(
            subject=subject,
            body=body,
            predicted_intents=intents,
            confidences=confidences,
            entities=entities,
            model_version=model_version,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
