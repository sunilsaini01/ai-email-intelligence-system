"""
Integration tests for the routing overrides CRUD API (Phase 21). Same
in-memory SQLite + get_db override pattern as test_mailbox_endpoints.py.
List stays open to any signed-in member; create/update/delete require an
org admin -- see tests/conftest.py's override_admin_auth for why that's a
separate fixture from the shared member one.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app
from tests.conftest import override_admin_auth, override_auth


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    override_auth(app)
    return TestClient(app)


@pytest.fixture
def admin_client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    override_admin_auth(app)
    return TestClient(app)


def _valid_payload(**overrides):
    payload = {
        "name": "VIP domain to Sales",
        "priority_order": 10,
        "is_active": True,
        "conditions": [{"field": "sender_email_domain", "operator": "eq", "value": "vip-client.com"}],
        "override_department": "Sales",
    }
    payload.update(overrides)
    return payload


def test_list_overrides_is_open_to_any_signed_in_member(client):
    response = client.get("/api/v1/routing/overrides")
    assert response.status_code == 200
    assert response.json()["overrides"] == []


def test_create_requires_an_admin(client):
    response = client.post("/api/v1/routing/overrides", json=_valid_payload())
    assert response.status_code == 403


def test_create_succeeds_for_an_admin_and_is_visible_to_a_member(admin_client, client):
    response = admin_client.post("/api/v1/routing/overrides", json=_valid_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "VIP domain to Sales"
    assert body["override_department"] == "Sales"
    assert body["conditions"] == [{"field": "sender_email_domain", "operator": "eq", "value": "vip-client.com"}]

    listed = client.get("/api/v1/routing/overrides").json()["overrides"]
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_create_rejects_an_override_with_no_conditions(admin_client):
    payload = _valid_payload()
    payload["conditions"] = []
    response = admin_client.post("/api/v1/routing/overrides", json=payload)
    assert response.status_code == 422


def test_create_rejects_an_override_that_changes_nothing(admin_client):
    payload = _valid_payload(override_department=None)
    response = admin_client.post("/api/v1/routing/overrides", json=payload)
    assert response.status_code == 422


def test_create_rejects_an_unknown_department(admin_client):
    payload = _valid_payload(override_department="NotARealDepartment")
    response = admin_client.post("/api/v1/routing/overrides", json=payload)
    assert response.status_code == 422


def test_create_rejects_an_unknown_condition_field(admin_client):
    payload = _valid_payload(conditions=[{"field": "not_a_real_field", "operator": "eq", "value": "x"}])
    response = admin_client.post("/api/v1/routing/overrides", json=payload)
    assert response.status_code == 422


def test_update_requires_an_admin(admin_client, client):
    override_id = admin_client.post("/api/v1/routing/overrides", json=_valid_payload()).json()["id"]
    response = client.put(f"/api/v1/routing/overrides/{override_id}", json={"is_active": False})
    assert response.status_code == 403


def test_update_only_changes_fields_actually_sent(admin_client):
    created = admin_client.post("/api/v1/routing/overrides", json=_valid_payload()).json()

    response = admin_client.put(f"/api/v1/routing/overrides/{created['id']}", json={"is_active": False})

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["name"] == created["name"]  # untouched
    assert body["priority_order"] == created["priority_order"]  # untouched


def test_update_unknown_override_returns_404(admin_client):
    response = admin_client.put(
        "/api/v1/routing/overrides/00000000-0000-0000-0000-000000000099", json={"is_active": False}
    )
    assert response.status_code == 404


def test_delete_requires_an_admin(admin_client, client):
    override_id = admin_client.post("/api/v1/routing/overrides", json=_valid_payload()).json()["id"]
    response = client.delete(f"/api/v1/routing/overrides/{override_id}")
    assert response.status_code == 403


def test_delete_removes_the_override(admin_client):
    override_id = admin_client.post("/api/v1/routing/overrides", json=_valid_payload()).json()["id"]

    response = admin_client.delete(f"/api/v1/routing/overrides/{override_id}")

    assert response.status_code == 204
    assert admin_client.get("/api/v1/routing/overrides").json()["overrides"] == []


def test_delete_unknown_override_returns_404(admin_client):
    response = admin_client.delete("/api/v1/routing/overrides/00000000-0000-0000-0000-000000000099")
    assert response.status_code == 404


class _FakeRoutingService:
    """Deterministic stand-in for RoutingService (see
    app/services/routing_service.py) -- this test exercises the OVERRIDE
    layer sitting in front of /routing/predict, not the real ML
    classifiers underneath it, so it deliberately does not depend on
    trained artifacts or model behavior (same "don't pin a test to a
    crafted input's actual model output" stance test_routing_endpoint.py's
    own module docstring already states, taken one step further: no real
    model call at all)."""

    def route(self, subject: str, body: str, sender_email: str = "") -> dict:
        return {
            "department": "Support",
            "action": "auto_route",
            "confidence": 0.8,
            "requires_human_review": False,
            "reason": "Category 'Support' auto-routed.",
            "matched_rules": ["R-CATEGORY-AUTO-ROUTE"],
            "supporting_signals": {
                "spam": {"is_spam": False, "confidence": 0.01, "reliability": "high"},
                "category": {"top": "Support", "confidence": 0.8, "reliability": "high"},
                "intent": {"labels": [], "reliability": "low"},
                "sentiment": None,
                "priority": None,
                "keywords": None,
                "sender_domain": {"type": "external", "reliability": "medium"},
            },
            "model_versions": {"spam": "v1", "category": "v1", "intent": None, "sentiment": None, "priority": None},
            "routing_rules_version": "routing_rules_v1",
            "keyword_matcher_version": "keyword_matcher_v1",
            "upstream_failures": [],
            "processing_ms": 1.0,
        }


def test_an_active_override_changes_a_real_predict_response(admin_client, client):
    from app.services.routing_service import get_routing_service

    admin_client.app.dependency_overrides[get_routing_service] = lambda: _FakeRoutingService()
    client.app.dependency_overrides[get_routing_service] = lambda: _FakeRoutingService()

    admin_client.post(
        "/api/v1/routing/overrides",
        json=_valid_payload(
            conditions=[{"field": "sender_email_domain", "operator": "eq", "value": "vip-client.com"}],
            override_department="IT",
        ),
    )

    response = client.post(
        "/api/v1/routing/predict", json={"subject": "Question", "body": "body", "sender_email": "person@vip-client.com"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["department"] == "IT"
    assert any(rule.startswith("OVERRIDE:") for rule in body["matched_rules"])


def test_an_override_for_a_different_sender_domain_does_not_fire(admin_client, client):
    from app.services.routing_service import get_routing_service

    admin_client.app.dependency_overrides[get_routing_service] = lambda: _FakeRoutingService()
    client.app.dependency_overrides[get_routing_service] = lambda: _FakeRoutingService()

    admin_client.post(
        "/api/v1/routing/overrides",
        json=_valid_payload(
            conditions=[{"field": "sender_email_domain", "operator": "eq", "value": "vip-client.com"}],
            override_department="IT",
        ),
    )

    response = client.post(
        "/api/v1/routing/predict", json={"subject": "Question", "body": "body", "sender_email": "person@somewhere-else.com"}
    )

    assert response.status_code == 200
    assert response.json()["department"] == "Support"  # the fake service's own base decision, untouched


def test_an_inactive_override_does_not_fire(admin_client, client):
    from app.services.routing_service import get_routing_service

    admin_client.app.dependency_overrides[get_routing_service] = lambda: _FakeRoutingService()
    client.app.dependency_overrides[get_routing_service] = lambda: _FakeRoutingService()

    admin_client.post(
        "/api/v1/routing/overrides",
        json=_valid_payload(
            is_active=False,
            conditions=[{"field": "sender_email_domain", "operator": "eq", "value": "vip-client.com"}],
            override_department="IT",
        ),
    )

    response = client.post(
        "/api/v1/routing/predict", json={"subject": "Question", "body": "body", "sender_email": "person@vip-client.com"}
    )

    assert response.json()["department"] == "Support"


def test_overrides_are_scoped_to_the_callers_organization(session_factory):
    """Same regression-test shape as test_reply_endpoint.py's own
    tenant-isolation test -- a signed-in admin of one organization must
    never see or manage another organization's overrides."""
    import uuid
    from datetime import UTC, datetime

    from app.core.auth_dependency import get_current_user, require_admin
    from app.models.user import ROLE_ADMIN, User

    def _client_for_org(organization_id: str) -> TestClient:
        async def override_get_db():
            async with session_factory() as session:
                yield session

        def _fake_admin() -> User:
            return User(
                id=uuid.uuid4(),
                email=f"admin@{organization_id}.example.com",
                hashed_password="unused",
                organization_id=organization_id,
                role=ROLE_ADMIN,
                is_active=True,
                created_at=datetime.now(UTC),
            )

        app = create_app()
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = _fake_admin
        app.dependency_overrides[require_admin] = _fake_admin
        return TestClient(app)

    org_a = _client_for_org("org-a")
    org_b = _client_for_org("org-b")

    override_id = org_a.post("/api/v1/routing/overrides", json=_valid_payload()).json()["id"]

    assert org_b.get("/api/v1/routing/overrides").json()["overrides"] == []
    assert org_b.put(f"/api/v1/routing/overrides/{override_id}", json={"is_active": False}).status_code == 404
    assert org_b.delete(f"/api/v1/routing/overrides/{override_id}").status_code == 404
