"""
Repository for category prediction audit logs. Same rationale as
priority_prediction_repository.py — the endpoint records a decision without
knowing the storage shape.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category_prediction_log import CategoryPredictionLog


class CategoryPredictionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_prediction(
        self,
        subject: str,
        body: str,
        categories: list[str],
        confidences: dict[str, float],
        model_version: str,
        processing_ms: float,
        organization_id: str | None = None,
    ) -> CategoryPredictionLog:
        # organization_id optional -- see spam_prediction_repository.py's
        # identical parameter for the full rationale.
        kwargs = {"organization_id": organization_id} if organization_id is not None else {}
        record = CategoryPredictionLog(
            **kwargs,
            subject=subject,
            body=body,
            predicted_categories=categories,
            confidences=confidences,
            model_version=model_version,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
