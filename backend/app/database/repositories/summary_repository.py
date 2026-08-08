"""Repository for summarization audit logs. Same rationale as the other
three modules' repositories — the endpoint records an outcome without
knowing the storage shape."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summary_log import SummaryLog


class SummaryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_summary(
        self,
        summary: str,
        summary_type: str,
        skipped_short_input: bool,
        input_word_count: int,
        entity_preservation_rate: float | None,
        model_version: str,
        processing_ms: float,
    ) -> SummaryLog:
        record = SummaryLog(
            summary=summary,
            summary_type=summary_type,
            skipped_short_input=skipped_short_input,
            input_word_count=input_word_count,
            entity_preservation_rate=entity_preservation_rate,
            model_version=model_version,
            processing_ms=processing_ms,
        )

        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

        return record
