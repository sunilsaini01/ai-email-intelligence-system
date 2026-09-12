"""Summarization Agent (Module 13 / Phase 12, FR-64). Wraps the existing,
unmodified SummarizationService.summarize() -- no ML logic duplicated."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.database.repositories.summary_repository import SummaryRepository
from app.services.summarization_service import get_summarization_service


class SummarizationAgent(BaseAgent):
    agent_name = "summarization"

    async def run_ml_call(self, payload: dict) -> dict:
        service = get_summarization_service()
        return await asyncio.to_thread(
            service.summarize, payload.get("subject", ""), payload.get("body", "")
        )

    async def persist_result(self, session: AsyncSession, organization_id: str, payload: dict, result: dict) -> None:
        # Exact same call app/api/v1/endpoints/summarization.py's
        # predict_summary makes -- see BaseAgent.persist_result's own
        # docstring for why this override exists at all.
        await SummaryRepository(session).log_summary(
            summary=result["summary"],
            summary_type=result["summary_type"],
            skipped_short_input=result["skipped_short_input"],
            input_word_count=result["input_word_count"],
            entity_preservation_rate=result["entity_preservation_rate"],
            model_version=result["model_version"],
            processing_ms=result["processing_ms"],
            organization_id=organization_id,
        )
