"""
Repository for the unified feedback/review event log (Module 11 / Phase 11).

Owns the one query every write-path caller needs beyond a plain insert:
"how many CORRECTIONs has this module accumulated since its last
retraining trigger" (FR-61) and "has this specific prediction already
been reviewed" (FR-60's review-queue exclusion) -- both narrow, table-
specific queries that belong here, same as every other repository in
this codebase. Broader cross-table aggregation (correction rate by
confidence bucket, etc.) lives in app/services/dashboard_service.py, the
analytics/query layer docs/architecture_dashboard.md's own architectural
principle calls for -- this repository stays a thin, single-table CRUD
layer, consistent with every other repository here.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback_event import ACTION_CORRECTION, FeedbackEvent


class FeedbackEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        module: str,
        action: str,
        organization_id: str,
        prediction_id: uuid.UUID | None = None,
        original_value=None,
        corrected_value=None,
        confidence: float | None = None,
        reviewer_id: str | None = None,
        reason: str | None = None,
    ) -> FeedbackEvent:
        record = FeedbackEvent(
            module=module,
            action=action,
            organization_id=organization_id,
            prediction_id=prediction_id,
            original_value=original_value,
            corrected_value=corrected_value,
            confidence=confidence,
            reviewer_id=reviewer_id,
            reason=reason,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def count_corrections_since(self, module: str, since: datetime | None) -> int:
        """Corrections for `module` after `since` (exclusive), or all-time
        if `since` is None -- the FR-61 threshold-crossing denominator."""
        query = select(func.count()).select_from(FeedbackEvent).where(
            FeedbackEvent.module == module, FeedbackEvent.action == ACTION_CORRECTION
        )
        if since is not None:
            query = query.where(FeedbackEvent.created_at > since)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def get_reviewed_prediction_ids(self, module: str, organization_id: str) -> set[uuid.UUID]:
        """Every prediction_id (CONFIRM or CORRECTION) already reviewed for
        this module -- used to exclude already-reviewed items from the
        Review Queue (FR-60)."""
        result = await self.session.execute(
            select(FeedbackEvent.prediction_id).where(
                FeedbackEvent.module == module,
                FeedbackEvent.organization_id == organization_id,
                FeedbackEvent.prediction_id.is_not(None),
            )
        )
        return {row[0] for row in result.all()}
