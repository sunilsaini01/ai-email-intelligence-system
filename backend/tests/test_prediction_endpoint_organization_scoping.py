"""
Regression tests for a real bug found while manually testing the running
Docker stack: none of the six direct prediction endpoints
(/spam/predict, /priority/predict, /category/predict, /sentiment/predict,
/intent/predict, /summarization/predict) derived organization_id from the
authenticated caller -- every prediction was logged under
DEFAULT_ORGANIZATION_ID ("default") no matter who called it or which
organization they belonged to. A user in organization "acme" calling
these endpoints would never see their own predictions on their own
dashboard (app/services/dashboard_service.py filters by organization_id).

Same in-memory SQLite + get_db override pattern as
test_mailbox_endpoints.py; a custom get_current_user override (not the
shared conftest.py one, which is always organization_id="default") signs
the caller in as organization "acme" specifically, so a passing test
proves the row landed under the CALLER's org, not merely under whatever
the model's own default happens to be.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.auth_dependency import get_current_user
from app.database.session import Base, get_db
from app.main import create_app
from app.models.user import ROLE_AGENT, User
from app.services.category_service import _DEFAULT_ARTIFACT_DIR as CATEGORY_DIR
from app.services.intent_service import _DEFAULT_ARTIFACT_DIR as INTENT_DIR
from app.services.priority_service import _DEFAULT_ARTIFACT_DIR as PRIORITY_DIR
from app.services.spam_service import _DEFAULT_ARTIFACT_DIR as SPAM_DIR

import uuid
from datetime import UTC, datetime

_REQUIRED_ARTIFACTS = [
    (SPAM_DIR, "spam_baseline.joblib"),
    (PRIORITY_DIR, "priority_baseline.joblib"),
    (CATEGORY_DIR, "category_baseline.joblib"),
    (INTENT_DIR, "intent_baseline.joblib"),
]

pytestmark = pytest.mark.skipif(
    not all((Path(d) / f).exists() for d, f in _REQUIRED_ARTIFACTS),
    reason="One or more of spam/priority/category/intent artifacts not found -- "
    "run the corresponding scripts/train_*.py first",
)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def acme_client(session_factory):
    def _fake_acme_user() -> User:
        return User(
            id=uuid.uuid4(),
            email="member@acme.example.com",
            hashed_password="unused",
            organization_id="acme",
            role=ROLE_AGENT,
            is_active=True,
            created_at=datetime.now(UTC),
        )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _fake_acme_user
    return TestClient(app), session_factory


@pytest.mark.asyncio
async def test_spam_predict_logs_under_the_callers_organization(acme_client):
    from sqlalchemy import select

    from app.models.spam_prediction_log import SpamPredictionLog

    client, session_factory = acme_client
    response = client.post("/api/v1/spam/predict", json={"subject": "test", "body": "test body"})
    assert response.status_code == 200

    async with session_factory() as session:
        rows = (await session.execute(select(SpamPredictionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].organization_id == "acme"


@pytest.mark.asyncio
async def test_priority_predict_logs_under_the_callers_organization(acme_client):
    from sqlalchemy import select

    from app.models.priority_prediction_log import PriorityPredictionLog

    client, session_factory = acme_client
    response = client.post("/api/v1/priority/predict", json={"subject": "test", "body": "test body"})
    assert response.status_code == 200

    async with session_factory() as session:
        rows = (await session.execute(select(PriorityPredictionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].organization_id == "acme"


@pytest.mark.asyncio
async def test_category_predict_logs_under_the_callers_organization(acme_client):
    from sqlalchemy import select

    from app.models.category_prediction_log import CategoryPredictionLog

    client, session_factory = acme_client
    response = client.post("/api/v1/categorization/predict", json={"subject": "test", "body": "test body"})
    assert response.status_code == 200

    async with session_factory() as session:
        rows = (await session.execute(select(CategoryPredictionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].organization_id == "acme"


@pytest.mark.asyncio
async def test_sentiment_predict_logs_under_the_callers_organization(acme_client):
    from sqlalchemy import select

    from app.models.sentiment_prediction_log import SentimentPredictionLog

    client, session_factory = acme_client
    response = client.post("/api/v1/sentiment/predict", json={"subject": "test", "body": "I am very happy"})
    assert response.status_code == 200

    async with session_factory() as session:
        rows = (await session.execute(select(SentimentPredictionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].organization_id == "acme"


@pytest.mark.asyncio
async def test_intent_predict_logs_under_the_callers_organization(acme_client):
    from sqlalchemy import select

    from app.models.intent_prediction_log import IntentPredictionLog

    client, session_factory = acme_client
    response = client.post("/api/v1/intent/predict", json={"subject": "test", "body": "I want a refund"})
    assert response.status_code == 200

    async with session_factory() as session:
        rows = (await session.execute(select(IntentPredictionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].organization_id == "acme"


@pytest.mark.asyncio
async def test_summarization_predict_logs_under_the_callers_organization(acme_client):
    from sqlalchemy import select

    from app.models.summary_log import SummaryLog

    client, session_factory = acme_client
    long_body = "This is a test sentence. " * 60  # comfortably over the short-input skip threshold
    response = client.post("/api/v1/summarization/predict", json={"subject": "test", "body": long_body})
    assert response.status_code == 200

    async with session_factory() as session:
        rows = (await session.execute(select(SummaryLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].organization_id == "acme"
