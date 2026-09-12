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
        organization_id: str | None = None,
    ) -> IntentPredictionLog:
        # organization_id optional -- see spam_prediction_repository.py's
        # identical parameter for the full rationale.
        kwargs = {"organization_id": organization_id} if organization_id is not None else {}
        record = IntentPredictionLog(
            **kwargs,
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
