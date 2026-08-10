"""Summarization Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified SummarizationService.summarize() -- no ML logic duplicated."""

import asyncio

from app.agents.base import BaseAgent
from app.services.summarization_service import get_summarization_service


class SummarizationAgent(BaseAgent):
    agent_name = "summarization"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_summarization_service()
        return await asyncio.to_thread(
            service.summarize, payload.get("subject", ""), payload.get("body", "")
        )
