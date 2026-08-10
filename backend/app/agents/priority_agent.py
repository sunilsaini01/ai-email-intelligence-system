"""Priority Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified PriorityService.classify() -- no ML logic duplicated."""

import asyncio

from app.agents.base import BaseAgent
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
