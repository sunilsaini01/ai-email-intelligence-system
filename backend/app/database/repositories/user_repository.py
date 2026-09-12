"""Repository for users (Phase 17, real authentication; count_for_organization
added in Phase 19, role-based authorization)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import ROLE_MEMBER, User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def count_for_organization(self, organization_id: str) -> int:
        """Phase 19: used at registration time to decide whether the new
        user is the FIRST account in this organization -- see
        app/api/v1/endpoints/auth.py's register() for why that matters
        (there is no admin yet to promote anyone, so the first account has
        to become one)."""
        result = await self.session.execute(
            select(func.count()).select_from(User).where(User.organization_id == organization_id)
        )
        return result.scalar_one()

    async def create(self, email: str, hashed_password: str, organization_id: str, role: str = ROLE_MEMBER) -> User:
        record = User(email=email, hashed_password=hashed_password, organization_id=organization_id, role=role)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record
