"""Category Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified CategoryService.classify() -- no ML logic duplicated."""

import asyncio

from app.agents.base import BaseAgent
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
