"""
Real auth-flow tests (Phase 17, real authentication).

Deliberately does NOT use the `client` fixture (conftest.py) -- that
fixture exists precisely to bypass auth for every OTHER test file's own
concerns. This file is the one place that must exercise the real thing:
register a real user, log in for a real token, and confirm both a
missing token and a wrong password are actually rejected. In-memory
SQLite via a get_db override, same isolation pattern as
test_dashboard_endpoint.py/test_reply_endpoint.py -- no real Postgres
needed, fully deterministic.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.main import create_app


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
    return TestClient(app)


def _register(client, email="user@example.com", password="correct-horse-battery", organization_name="Acme"):
    """Public signup -- always creates a NEW organization (membership
    security fix); joining an existing one needs an invitation."""
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "organization_name": organization_name},
    )


def _invite_and_accept(client, admin_token, email, role="agent", password="correct-horse-battery"):
    invitation = client.post(
        "/api/v1/admin/invitations",
        json={"email": email, "role": role},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert invitation.status_code == 201, invitation.text
    return client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": invitation.json()["token"], "email": email, "password": password},
    )


def _login(client, email="user@example.com", password="correct-horse-battery"):
    # OAuth2PasswordRequestForm -- form-encoded, not JSON, "username" holds the email.
    return client.post("/api/v1/auth/login", data={"username": email, "password": password})


def test_register_creates_a_user_and_hashes_the_password(client):
    response = _register(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "user@example.com"
    assert body["organization_id"].startswith("org_")  # server-generated
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_rejects_duplicate_email(client):
    _register(client)
    response = _register(client)
    assert response.status_code == 409


def test_register_rejects_short_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": "short", "organization_name": "Acme"},
    )
    assert response.status_code == 422


def test_login_with_correct_credentials_returns_a_usable_token(client):
    _register(client)
    response = _login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20


def test_login_with_wrong_password_is_rejected(client):
    _register(client)
    response = _login(client, password="wrong-password-entirely")
    assert response.status_code == 401


def test_login_with_unknown_email_is_rejected_with_the_same_error_as_wrong_password(client):
    """Same status/detail for both cases -- see app/api/v1/endpoints/auth.py's
    own comment on why distinguishing them would let an attacker enumerate
    valid emails."""
    unknown = client.post("/api/v1/auth/login", data={"username": "nobody@example.com", "password": "whatever123"})
    _register(client)
    wrong_password = _login(client, password="wrong-password-entirely")
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


def test_protected_endpoint_without_a_token_is_rejected(client):
    response = client.post("/api/v1/priority/predict", json={"subject": "test", "body": "test"})
    assert response.status_code == 401


def test_protected_endpoint_with_a_valid_token_succeeds(client):
    _register(client)
    token = _login(client).json()["access_token"]

    response = client.post(
        "/api/v1/priority/predict",
        json={"subject": "test", "body": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_protected_endpoint_with_a_malformed_token_is_rejected(client):
    response = client.post(
        "/api/v1/priority/predict",
        json={"subject": "test", "body": "test"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert response.status_code == 401


def test_health_endpoint_requires_no_token(client):
    """Liveness must stay reachable with no auth at all -- see
    app/api/v1/endpoints/health.py's own module docstring on why /health
    must never gate on anything, extended here to mean "not even auth."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_me_returns_the_authenticated_users_own_identity(client):
    org_id = _register(client, email="me@example.com").json()["organization_id"]
    token = _login(client, email="me@example.com").json()["access_token"]

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["organization_id"] == org_id


# --- Phase 19: role-based authorization -------------------------------


def test_the_organization_creator_becomes_its_admin(client):
    response = _register(client, email="founder@acme.com")
    assert response.json()["role"] == "admin"


def test_an_invited_teammate_gets_the_invited_role_in_the_inviters_organization(client):
    founder = _register(client, email="founder@acme.com").json()
    admin_token = _login(client, email="founder@acme.com").json()["access_token"]
    teammate = _invite_and_accept(client, admin_token, "teammate@acme.com")
    assert teammate.status_code == 201
    assert teammate.json()["role"] == "agent"
    assert teammate.json()["organization_id"] == founder["organization_id"]


def test_each_signup_creates_a_separate_organization(client):
    """Two signups naming the same organization still get two different,
    server-generated organizations -- a name never grants membership."""
    first = _register(client, email="founder@acme.com", organization_name="Acme").json()
    second = _register(client, email="other@acme.com", organization_name="Acme").json()
    assert first["organization_id"] != second["organization_id"]
    assert second["role"] == "admin"


def test_an_admin_gated_endpoint_rejects_a_member_and_allows_an_admin(client, monkeypatch):
    """Exercises the real thing end-to-end (register -> login -> call a
    require_admin-gated route) rather than the conftest.py fixture
    overrides every other test file uses -- same "this file is the one
    place that verifies the real auth boundary" stance this module's own
    docstring already states, extended to the admin boundary. Uses
    /mailbox/gmail/connect (Phase 18) as a real, already-existing
    require_admin-gated endpoint; Gmail's own provider construction is
    monkeypatched so the test asserts on the authorization boundary, not
    on whether Gmail credentials happen to be configured."""
    from app.ingestion.fake_mailbox_provider import FakeMailboxProvider

    monkeypatch.setattr("app.api.v1.endpoints.mailbox.build_provider", lambda provider: FakeMailboxProvider())

    _register(client, email="founder@acme.com")
    admin_token = _login(client, email="founder@acme.com").json()["access_token"]
    _invite_and_accept(client, admin_token, "agent@acme.com")
    member_token = _login(client, email="agent@acme.com").json()["access_token"]

    member_response = client.get("/api/v1/mailbox/gmail/connect", headers={"Authorization": f"Bearer {member_token}"})
    assert member_response.status_code == 403

    admin_response = client.get("/api/v1/mailbox/gmail/connect", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_response.status_code == 200
