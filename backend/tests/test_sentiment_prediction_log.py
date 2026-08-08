"""
Tests for the sentiment prediction audit log (Module 6), mirroring
test_priority_prediction_log.py. Unlike SummaryLog, SentimentPredictionLog
DOES store subject/body directly (same reasoning as spam/priority/category
-- no `emails` table exists yet, see that model's docstring), so this also
locks in that fact structurally rather than leaving it to convention.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.sentiment_prediction_log import SentimentPredictionLog
from app.services.sentiment_service import get_sentiment_service


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
    get_sentiment_service.cache_clear()

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app), sqlite_session_factory

    app.dependency_overrides.clear()
    get_sentiment_service.cache_clear()


@pytest.mark.asyncio
async def test_prediction_is_persisted(db_client):
    client, session_factory = db_client

    response = client.post(
        "/api/v1/sentiment/predict",
        json={
            "subject": "Frustrated",
            "body": "This is the third time this has happened and it is unacceptable.",
        },
    )
    assert response.status_code == 200
    body = response.json()

    async with session_factory() as session:
        result = await session.execute(select(SentimentPredictionLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.predicted_sentiment == body["sentiment"]
    assert row.model_version == body["model_version"]
    assert row.subject == "Frustrated"
    assert row.body == "This is the third time this has happened and it is unacceptable."
    assert row.synthetic_model is True
    assert row.created_at is not None
