"""Intent Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified IntentService.analyze() -- no ML logic duplicated."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.database.repositories.intent_prediction_repository import IntentPredictionRepository
from app.services.intent_service import get_intent_service


class IntentAgent(BaseAgent):
    agent_name = "intent"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_intent_service()
        return await asyncio.to_thread(
            service.analyze, payload.get("subject", ""), payload.get("body", "")
        )

    async def persist_result(self, session: AsyncSession, organization_id: str, payload: dict, result: dict) -> None:
        # Same intents/confidences/entities extraction
        # app/api/v1/endpoints/intent.py's predict_intent makes -- see
        # BaseAgent.persist_result's own docstring for why this override
        # exists at all.
        await IntentPredictionRepository(session).log_prediction(
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            intents=[i["intent"] for i in result["intents"]],
            confidences={i["intent"]: i["confidence"] for i in result["intents"]},
            entities=result["entities"],
            model_version=result["model_version"],
            processing_ms=result["processing_ms"],
            organization_id=organization_id,
        )
