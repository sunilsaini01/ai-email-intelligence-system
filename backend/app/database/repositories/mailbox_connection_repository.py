"""Repository for mailbox_connections (Phase 18, live mailbox ingestion)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mailbox_connection import STATUS_ACTIVE, STATUS_ERROR, MailboxConnection


class MailboxConnectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self,
        *,
        organization_id: str,
        connected_by_user_id: uuid.UUID,
        provider: str,
        email_address: str,
        access_token_encrypted: str | None,
        access_token_expires_at: datetime | None,
        refresh_token_encrypted: str,
    ) -> MailboxConnection:
        """Reconnecting the same (org, provider, email_address) refreshes
        tokens on the existing row rather than creating a duplicate poller
        for it -- see the model's own UniqueConstraint. Re-activates a
        previously errored/revoked connection: the user explicitly
        re-authorized it, which is exactly the recovery action for both of
        those states."""
        existing = await self._get_by_identity(organization_id, provider, email_address)
        if existing is not None:
            existing.connected_by_user_id = connected_by_user_id
            existing.access_token_encrypted = access_token_encrypted
            existing.access_token_expires_at = access_token_expires_at
            existing.refresh_token_encrypted = refresh_token_encrypted
            existing.status = STATUS_ACTIVE
            existing.last_error = None
            existing.is_deleted = False
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        record = MailboxConnection(
            organization_id=organization_id,
            connected_by_user_id=connected_by_user_id,
            provider=provider,
            email_address=email_address,
            access_token_encrypted=access_token_encrypted,
            access_token_expires_at=access_token_expires_at,
            refresh_token_encrypted=refresh_token_encrypted,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def _get_by_identity(self, organization_id: str, provider: str, email_address: str) -> MailboxConnection | None:
        result = await self.session.execute(
            select(MailboxConnection).where(
                MailboxConnection.organization_id == organization_id,
                MailboxConnection.provider == provider,
                MailboxConnection.email_address == email_address,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: str) -> list[MailboxConnection]:
        result = await self.session.execute(
            select(MailboxConnection).where(
                MailboxConnection.organization_id == organization_id,
                MailboxConnection.is_deleted.is_(False),
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, organization_id: str, connection_id: uuid.UUID) -> MailboxConnection | None:
        result = await self.session.execute(
            select(MailboxConnection).where(
                MailboxConnection.id == connection_id,
                MailboxConnection.organization_id == organization_id,
                MailboxConnection.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_all_active(self) -> list[MailboxConnection]:
        """Cross-organization -- the poller (app/agents/runner.py) polls
        every connected mailbox regardless of which org owns it, same
        scope as every other agents-process background task."""
        result = await self.session.execute(
            select(MailboxConnection).where(
                MailboxConnection.status == STATUS_ACTIVE,
                MailboxConnection.is_deleted.is_(False),
            )
        )
        return list(result.scalars().all())

    async def soft_delete(self, connection: MailboxConnection) -> None:
        connection.is_deleted = True
        await self.session.commit()

    async def update_tokens(
        self,
        connection: MailboxConnection,
        *,
        access_token_encrypted: str,
        access_token_expires_at: datetime,
        refresh_token_encrypted: str | None = None,
    ) -> None:
        """`refresh_token_encrypted` is optional -- Google/Microsoft do not
        always issue a new refresh token on every refresh grant (Google
        specifically only issues one on the FIRST authorization unless
        `access_type=offline&prompt=consent` forces a new one every time);
        keep the existing one when the provider doesn't send a new one."""
        connection.access_token_encrypted = access_token_encrypted
        connection.access_token_expires_at = access_token_expires_at
        if refresh_token_encrypted is not None:
            connection.refresh_token_encrypted = refresh_token_encrypted
        await self.session.commit()

    async def update_sync_cursor(self, connection: MailboxConnection, sync_cursor: str) -> None:
        connection.sync_cursor = sync_cursor
        connection.last_synced_at = datetime.now(UTC)
        await self.session.commit()

    async def mark_error(self, connection: MailboxConnection, error: str) -> None:
        connection.status = STATUS_ERROR
        connection.last_error = error[:2000]
        await self.session.commit()

    async def count_errored(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(MailboxConnection).where(
                MailboxConnection.status == STATUS_ERROR,
                MailboxConnection.is_deleted.is_(False),
            )
        )
        return result.scalar_one()
