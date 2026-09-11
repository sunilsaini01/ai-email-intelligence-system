"""Repository for mailbox_ingested_messages (Phase 18) -- see that model's
own module docstring for why this dedup ledger exists."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mailbox_ingested_message import MailboxIngestedMessage


class MailboxIngestedMessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_already_ingested(self, connection_id: uuid.UUID, provider_message_id: str) -> bool:
        result = await self.session.execute(
            select(MailboxIngestedMessage.id).where(
                MailboxIngestedMessage.connection_id == connection_id,
                MailboxIngestedMessage.provider_message_id == provider_message_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def record(self, connection_id: uuid.UUID, provider_message_id: str, workflow_id: uuid.UUID) -> None:
        self.session.add(
            MailboxIngestedMessage(
                connection_id=connection_id, provider_message_id=provider_message_id, workflow_id=workflow_id
            )
        )
        await self.session.commit()
