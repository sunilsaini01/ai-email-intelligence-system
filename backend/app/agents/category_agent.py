"""Category Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified CategoryService.classify() -- no ML logic duplicated."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.database.repositories.category_prediction_repository import CategoryPredictionRepository
from app.services.category_service import get_category_service


class CategoryAgent(BaseAgent):
    agent_name = "category"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_category_service()
        return await asyncio.to_thread(
            service.classify,
            payload.get("subject", ""),
            payload.get("body", ""),
            payload.get("sender_email", ""),
        )

    async def persist_result(self, session: AsyncSession, organization_id: str, payload: dict, result: dict) -> None:
        # Same categories/confidences extraction
        # app/api/v1/endpoints/category.py's predict_category makes --
        # see BaseAgent.persist_result's own docstring for why this
        # override exists at all.
        categories = [c["category"] for c in result["categories"]]
        confidences = {c["category"]: c["confidence"] for c in result["categories"]}
        await CategoryPredictionRepository(session).log_prediction(
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            categories=categories,
            confidences=confidences,
            model_version=result["model_version"],
            processing_ms=result["processing_ms"],
            organization_id=organization_id,
        )
