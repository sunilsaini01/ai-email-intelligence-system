"""
Tests for the routing decision audit log (Module 8 / Phase 8), mirroring
test_intent_prediction_log.py. Uses fake upstream services (not real
artifacts) since this test is about DB persistence, not model behavior --
same rationale as test_routing_service.py.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from app.models.routing_decision_log import RoutingDecisionLog
from app.services.routing_service import RoutingService, get_routing_service
from tests.test_routing_service import _category, _intent, _priority, _sentiment, _spam


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
    get_routing_service.cache_clear()

    fake_routing_service = RoutingService(
        spam_service=type("F", (), {"classify": staticmethod(lambda s, b: _spam())})(),
        category_service=type(
            "F", (), {"classify": staticmethod(lambda s, b, sender_email="": _category(top="Billing", top_conf=0.9))}
        )(),
        intent_service=type("F", (), {"analyze": staticmethod(lambda s, b: _intent(("Refund",)))})(),
        sentiment_service=type("F", (), {"analyze": staticmethod(lambda s, b: _sentiment())})(),
        priority_service=type(
            "F", (), {"classify": staticmethod(lambda s, b, sender_email="": _priority())}
        )(),
    )

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_routing_service] = lambda: fake_routing_service

    yield TestClient(app), sqlite_session_factory

    app.dependency_overrides.clear()
    get_routing_service.cache_clear()


@pytest.mark.asyncio
async def test_routing_decision_is_persisted(db_client):
    client, session_factory = db_client

    response = client.post(
        "/api/v1/routing/predict",
        json={"subject": "Refund", "body": "Please refund my last payment.", "sender_email": "a@b.com"},
    )
    assert response.status_code == 200
    body = response.json()

    async with session_factory() as session:
        result = await session.execute(select(RoutingDecisionLog))
        rows = result.scalars().all()

    assert len(rows) == 1
    row = rows[0]
    assert row.department == body["department"] == "Billing"
    assert row.action == body["action"]
    assert row.matched_rules == body["matched_rules"]
    assert row.routing_rules_version == "routing_rules_v1"
    assert row.synthetic_model is True
    assert row.created_at is not None
    assert "R-REFUND-BILLING-CORROBORATED" in row.matched_rules
