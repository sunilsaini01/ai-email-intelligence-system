"""Sentiment Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified SentimentService.analyze() -- no ML logic duplicated."""

import asyncio

from app.agents.base import BaseAgent
from app.services.sentiment_service import get_sentiment_service


class SentimentAgent(BaseAgent):
    agent_name = "sentiment"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_sentiment_service()
        return await asyncio.to_thread(
            service.analyze, payload.get("subject", ""), payload.get("body", "")
        )
