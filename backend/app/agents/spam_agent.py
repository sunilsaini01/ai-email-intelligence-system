"""Spam Agent (Module 13 / Phase 12, FR-64). Wraps the existing, unmodified
SpamService.classify() -- no ML logic duplicated, per Critical Rule #6."""

import asyncio

from app.agents.base import BaseAgent
from app.services.spam_service import get_spam_service


class SpamAgent(BaseAgent):
    agent_name = "spam"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_spam_service()
        return await asyncio.to_thread(
            service.classify, payload.get("subject", ""), payload.get("body", "")
        )
