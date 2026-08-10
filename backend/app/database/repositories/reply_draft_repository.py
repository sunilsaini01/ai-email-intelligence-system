"""
Repository for `reply_drafts` (Module 10 / Phase 10).

Every method here either creates a draft (always, even on generation
failure -- Step 8's audit-trail requirement) or transitions its lifecycle
(APPROVE/EDIT/REJECT, Step 8) -- no method silently overwrites
`generated_text`, matching every other repository's "write once, then
explicit state transitions" shape (EmailRepository's index_status machine
is the closest precedent).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reply_draft import (
    STATUS_APPROVED,
    STATUS_EDITED,
    STATUS_REJECTED,
    ReplyDraft,
)
from app.nlp.edit_distance import compute_edit_distance


class ReplyDraftRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields) -> ReplyDraft:
        draft = ReplyDraft(**fields)
        self.session.add(draft)
        await self.session.commit()
        await self.session.refresh(draft)
        return draft

    async def get_by_id(self, organization_id: str, draft_id: uuid.UUID) -> ReplyDraft | None:
        result = await self.session.execute(
            select(ReplyDraft).where(
                ReplyDraft.organization_id == organization_id,
                ReplyDraft.id == draft_id,
            )
        )
        return result.scalar_one_or_none()

    async def approve(self, draft: ReplyDraft, reviewer_id: str | None) -> ReplyDraft:
        draft.status = STATUS_APPROVED
        draft.reviewer_id = reviewer_id
        draft.reviewed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(draft)
        return draft

    async def edit(self, draft: ReplyDraft, edited_text: str, reviewer_id: str | None) -> ReplyDraft:
        draft.status = STATUS_EDITED
        draft.edited_text = edited_text
        draft.edit_distance = compute_edit_distance(draft.generated_text or "", edited_text)
        draft.reviewer_id = reviewer_id
        draft.reviewed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(draft)
        return draft

    async def reject(self, draft: ReplyDraft, reviewer_id: str | None) -> ReplyDraft:
        draft.status = STATUS_REJECTED
        draft.reviewer_id = reviewer_id
        draft.reviewed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(draft)
        return draft
