"""
Tests for the intent prediction audit log (Module 7), mirroring
test_category_prediction_log.py.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.intent_prediction_log import IntentPredictionLog
from app.services.intent_service import _DEFAULT_ARTIFACT_DIR, get_intent_service

pytestmark = pytest.mark.skipif(
    not (Path(_DEFAULT_ARTIFACT_DIR) / "intent_baseline.joblib").exists(),
    reason="intent_baseline.joblib not found — run scripts/train_intent_model.py first",
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
    get_intent_service.cache_clear()

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app), sqlite_session_factory

    app.dependency_overrides.clear()
    get_intent_service.cache_clear()


@pytest.mark.asyncio
async def test_prediction_is_persisted_with_entities(db_client):
    client, session_factory = db_client

    response = client.post(
        "/api/v1/intent/predict",
        json={
            "subject": "Cancel",
            "body": "Please cancel my subscription and refund order #45821.",
        },
    )
    assert response.status_code == 200
    body = response.json()

    async with session_factory() as session:
        result = await session.execute(select(IntentPredictionLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.predicted_intents == [i["intent"] for i in body["intents"]]
    assert row.model_version == body["model_version"]
    assert row.subject == "Cancel"
    assert row.entities["order_ids"] == ["45821"]
    assert row.synthetic_model is True
    assert row.created_at is not None
