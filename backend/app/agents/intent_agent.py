"""Intent Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified IntentService.analyze() -- no ML logic duplicated."""

import asyncio

from app.agents.base import BaseAgent
from app.services.intent_service import get_intent_service


class IntentAgent(BaseAgent):
    agent_name = "intent"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_intent_service()
        return await asyncio.to_thread(
            service.analyze, payload.get("subject", ""), payload.get("body", "")
        )
