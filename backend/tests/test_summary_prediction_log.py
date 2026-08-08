"""
Tests for the summary audit log (Module 5), mirroring
test_priority_prediction_log.py / test_category_prediction_log.py — same
reasoning for the in-memory SQLite session override. Also locks in the
Step-16 privacy decision: no source body/subject is ever persisted.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.summary_log import SummaryLog


def _long_body(word_count: int = 250) -> str:
    return ". ".join(f"This is filler sentence number {i} in a long email" for i in range(word_count // 8)) + "."


@pytest_asyncio.fixture
async def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    yield session_factory

    await engine.dispose()


@pytest.fixture
def db_client(sqlite_session_factory):
    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app), sqlite_session_factory

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_summary_prediction_is_persisted(db_client):
    client, session_factory = db_client

    secret_body = _long_body(300) + " CONFIDENTIAL: internal salary figures attached."
    response = client.post(
        "/api/v1/summarization/predict",
        json={"subject": "Confidential memo", "body": secret_body},
    )
    assert response.status_code == 200
    body = response.json()

    async with session_factory() as session:
        result = await session.execute(select(SummaryLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.summary == body["summary"]
    assert row.summary_type == body["summary_type"]
    assert row.model_version == body["model_version"]
    assert row.created_at is not None


@pytest.mark.asyncio
async def test_summary_log_table_has_no_source_body_column(db_client):
    """Step 16's explicit instruction: don't duplicate sensitive source
    content. Locked in structurally, not just by convention — if a future
    change adds a body/subject column to SummaryLog, this test should
    prompt re-reading that decision, not silently pass."""
    from sqlalchemy import inspect

    columns = {c.name for c in inspect(SummaryLog).columns}
    assert "body" not in columns
    assert "subject" not in columns
    assert "summary" in columns  # the output IS stored
