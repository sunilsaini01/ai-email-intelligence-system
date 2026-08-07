"""
Database session management.

Why async SQLAlchemy (AsyncSession) instead of sync:
    FastAPI route handlers are async. If you call a sync DB driver inside an
    async route, that call blocks the event loop thread — every other
    concurrent request stalls behind your DB query. asyncpg + SQLAlchemy's
    async engine lets the event loop serve other requests while waiting on I/O.

Why a dependency-injected session, not a global session object:
    A single shared Session is NOT thread/coroutine-safe — concurrent requests
    sharing one session corrupt each other's transactions. Each request must
    get its own session, used for exactly that request's lifetime, then closed.
    That's what `get_db` below provides via FastAPI's Depends().

Production note:
    pool_size / max_overflow matter once you have real concurrency. Defaults
    here are conservative; tune against actual load testing, not guesswork.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,       # logs raw SQL — useful locally, turn off in prod (noisy + perf cost)
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,        # detects stale/dropped connections before using them
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    """Declarative base — every ORM model in app/models/ inherits from this."""
    pass


# Bounds how long an endpoint's best-effort audit-log write (spam/priority
# prediction repositories) is allowed to block a response. Discovered as a
# real gap, not designed in from the start: a *raised* DB exception (e.g.
# auth failure) was already caught by the endpoints' try/except and didn't
# block the response — but a *hanging* connection attempt (observed against
# a local Postgres with what appears to be an IPv6 routing issue) has no
# exception to catch, so the request hung indefinitely instead of failing
# fast. Wrap any such best-effort write in
# `asyncio.wait_for(..., timeout=DB_WRITE_TIMEOUT_SECONDS)` — 3s is generous
# for a local network write (predictions themselves complete in
# single-digit ms) while still bounding the worst case to something a
# caller can reasonably wait out.
DB_WRITE_TIMEOUT_SECONDS = 3.0


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency. Yields a session scoped to a single request,
    guarantees it's closed afterward even if the request raises.
    """
    async with AsyncSessionLocal() as session:
        yield session
