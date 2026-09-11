"""Repository for users (Phase 17, real authentication)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, email: str, hashed_password: str, organization_id: str) -> User:
        record = User(email=email, hashed_password=hashed_password, organization_id=organization_id)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record
