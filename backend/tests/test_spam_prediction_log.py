"""
Tests for the spam prediction audit log (Module 10).

Why this doesn't use the shared `client` fixture:
    That fixture builds the app against the real (Postgres) `get_db`
    dependency, which isn't reachable in this dev environment — and the
    endpoint deliberately swallows DB failures so predictions still work
    without a DB (see app/api/v1/endpoints/spam.py). That means the shared
    fixture would pass even if logging were completely broken. This fixture
    overrides `get_db` with an in-memory SQLite session so the DB write path
    is actually exercised, not just skipped past.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.spam_prediction_log import SpamPredictionLog
from app.services.spam_service import _DEFAULT_ARTIFACT_DIR, get_spam_service

pytestmark = pytest.mark.skipif(
    not (Path(_DEFAULT_ARTIFACT_DIR) / "spam_baseline.joblib").exists(),
    reason="spam_baseline.joblib not found — run scripts/train_spam_model.py first",
)


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
    get_spam_service.cache_clear()

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app), sqlite_session_factory

    app.dependency_overrides.clear()
    get_spam_service.cache_clear()


@pytest.mark.asyncio
async def test_prediction_is_persisted(db_client):
    client, session_factory = db_client

    response = client.post(
        "/api/v1/spam/predict",
        json={
            "subject": "URGENT: You have won a free prize!!!",
            "body": "Click here now to claim your free iPhone. Limited time offer, act now!",
        },
    )
    assert response.status_code == 200
    body = response.json()

    async with session_factory() as session:
        result = await session.execute(select(SpamPredictionLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.is_spam == body["is_spam"]
    assert row.status == body["status"]
    assert row.model_version == body["model_version"]
    assert row.subject == "URGENT: You have won a free prize!!!"
    assert row.created_at is not None
