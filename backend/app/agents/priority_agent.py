"""Priority Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified PriorityService.classify() -- no ML logic duplicated."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.database.repositories.priority_prediction_repository import PriorityPredictionRepository
from app.services.priority_service import get_priority_service


class PriorityAgent(BaseAgent):
    agent_name = "priority"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_priority_service()
        return await asyncio.to_thread(
            service.classify,
            payload.get("subject", ""),
            payload.get("body", ""),
            payload.get("sender_email", ""),
        )

    async def persist_result(self, session: AsyncSession, organization_id: str, payload: dict, result: dict) -> None:
        # Exact same call app/api/v1/endpoints/priority.py's
        # predict_priority makes -- see BaseAgent.persist_result's own
        # docstring for why this override exists at all.
        await PriorityPredictionRepository(session).log_prediction(
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            priority=result["priority"],
            confidence=result["confidence"],
            model_version=result["model_version"],
            processing_ms=result["processing_ms"],
            organization_id=organization_id,
        )
