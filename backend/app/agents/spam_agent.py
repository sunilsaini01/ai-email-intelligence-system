"""Spam Agent (Module 13 / Phase 12, FR-64). Wraps the existing, unmodified
SpamService.classify() -- no ML logic duplicated, per Critical Rule #6."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.database.repositories.spam_prediction_repository import SpamPredictionRepository
from app.services.spam_service import get_spam_service


class SpamAgent(BaseAgent):
    agent_name = "spam"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_spam_service()
        return await asyncio.to_thread(
            service.classify, payload.get("subject", ""), payload.get("body", "")
        )

    async def persist_result(self, session: AsyncSession, organization_id: str, payload: dict, result: dict) -> None:
        # Exact same call app/api/v1/endpoints/spam.py's predict_spam
        # makes -- see BaseAgent.persist_result's own docstring for why
        # this override exists at all.
        await SpamPredictionRepository(session).log_prediction(
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            organization_id=organization_id,
            **result,
        )
