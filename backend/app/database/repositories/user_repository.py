"""Repository for users (Phase 17, real authentication). Account creation
lives in app/services/membership_service.py -- the only two sanctioned
ways an account joins an organization."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger("app.auth")


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        """Case-insensitive lookup -- new accounts are stored lower-cased,
        legacy rows may not be.

        Fails CLOSED on ambiguity: if legacy data holds several accounts
        that differ only by case (possible before uq_users_email_lower),
        returns None rather than guessing, so login answers with the normal
        invalid-credentials response instead of signing someone into
        whichever row happened to come first. Operators resolve these with
        scripts/audit_organization_memberships.py (see
        docs/security/organization_membership_remediation.md)."""
        result = await self.session.execute(
            select(User).where(func.lower(User.email) == email.strip().lower()).limit(2)
        )
        matches = list(result.scalars())
        if len(matches) > 1:
            logger.warning(
                "login_email_ambiguous",
                extra={"user_ids": sorted(str(u.id) for u in matches)},
            )
            return None
        return matches[0] if matches else None
