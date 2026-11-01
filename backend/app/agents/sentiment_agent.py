"""Sentiment Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified SentimentService.analyze() -- no ML logic duplicated."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.database.repositories.sentiment_repository import SentimentPredictionRepository
from app.services.sentiment_service import get_sentiment_service


class SentimentAgent(BaseAgent):
    agent_name = "sentiment"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_sentiment_service()
        return await asyncio.to_thread(
            service.analyze, payload.get("subject", ""), payload.get("body", "")
        )

    async def persist_result(self, session: AsyncSession, organization_id: str, payload: dict, result: dict) -> None:
        # Exact same call app/api/v1/endpoints/sentiment.py's
        # predict_sentiment makes -- see BaseAgent.persist_result's own
        # docstring for why this override exists at all.
        await SentimentPredictionRepository(session).log_prediction(
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            sentiment=result["sentiment"],
            confidence=result["confidence"],
            model_version=result["model_version"],
            processing_ms=result["processing_ms"],
            organization_id=organization_id,
            sender_email=payload.get("sender_email", ""),
            primary_emotion=result.get("primary_emotion"),
            emotions=result.get("emotions"),
        )
