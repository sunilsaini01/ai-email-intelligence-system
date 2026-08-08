"""
Tests for the category prediction audit log (Module 4), mirroring
test_priority_prediction_log.py — same reasoning for not using the shared
`client` fixture alone (needs get_db overridden with an in-memory SQLite
session to actually exercise the DB write path, not skip past it).
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.category_prediction_log import CategoryPredictionLog
from app.services.category_service import _DEFAULT_ARTIFACT_DIR, get_category_service

pytestmark = pytest.mark.skipif(
    not (Path(_DEFAULT_ARTIFACT_DIR) / "category_baseline.joblib").exists(),
    reason="category_baseline.joblib not found — run scripts/train_category_model.py first",
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
    get_category_service.cache_clear()

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    yield TestClient(app), sqlite_session_factory

    app.dependency_overrides.clear()
    get_category_service.cache_clear()


@pytest.mark.asyncio
async def test_prediction_is_persisted(db_client):
    client, session_factory = db_client

    response = client.post(
        "/api/v1/categorization/predict",
        json={
            "subject": "Invoice past due, please review contract terms",
            "body": "This invoice is overdue and legal needs to review the contract terms before we pay.",
        },
    )
    assert response.status_code == 200
    body = response.json()

    async with session_factory() as session:
        result = await session.execute(select(CategoryPredictionLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.predicted_categories == [c["category"] for c in body["categories"]]
    assert row.model_version == body["model_version"]
    assert row.subject == "Invoice past due, please review contract terms"
    assert row.created_at is not None
