"""
Integration tests for the mailbox connect/callback/list/disconnect
endpoints (Phase 18). Same in-memory SQLite + get_db override pattern as
tests/test_dashboard_endpoint.py. `list` goes through the normal
get_current_user override; `connect`/`disconnect` require an ORG ADMIN as
of Phase 19 (role-based authorization), so their tests use `admin_client`
instead of the plain member `client` -- see tests/conftest.py's
override_admin_auth for why that's a separate fixture rather than a role
swap on the same one. `callback` is not behind either dependency at all
(see app/api/v1/router.py's own docstring on why) -- its tests instead
mint a real signed state token via app/ingestion/oauth_state.build_state
directly, the same thing `connect` does internally.
"""

from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.ingestion.fake_mailbox_provider import FakeMailboxProvider
from app.ingestion.gmail_provider import GmailProviderUnavailable
from app.ingestion.oauth_state import build_state
from app.main import create_app
from tests.conftest import TEST_ADMIN_USER_ID, TEST_USER_ID, override_admin_auth, override_auth


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
    """Same in-memory database as `client` above -- built from the SAME
    session_factory fixture instance, so an admin_client request and a
    plain client request within one test see the same data. Only the
    signed-in identity differs."""

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    override_admin_auth(app)
    return TestClient(app)


def _state_query_param(authorization_url: str) -> str:
    return parse_qs(urlparse(authorization_url).query)["state"][0]


def test_connect_rejects_an_unknown_provider(admin_client):
    response = admin_client.get("/api/v1/mailbox/yahoo/connect")
    assert response.status_code == 404


def test_connect_returns_503_when_the_provider_is_not_configured(admin_client, monkeypatch):
    def raise_unavailable(provider):
        raise GmailProviderUnavailable("Gmail is not configured.")

    monkeypatch.setattr("app.api.v1.endpoints.mailbox.build_provider", raise_unavailable)

    response = admin_client.get("/api/v1/mailbox/gmail/connect")

    assert response.status_code == 503


def test_connect_returns_an_authorization_url_carrying_a_verifiable_state(admin_client, monkeypatch):
    fake = FakeMailboxProvider()
    monkeypatch.setattr("app.api.v1.endpoints.mailbox.build_provider", lambda provider: fake)

    response = admin_client.get("/api/v1/mailbox/gmail/connect")

    assert response.status_code == 200
    authorization_url = response.json()["authorization_url"]
    assert authorization_url in fake.authorization_urls_built

    from app.ingestion.oauth_state import verify_state

    organization_id, user_id = verify_state(_state_query_param(authorization_url), expected_provider="gmail")
    assert user_id == TEST_ADMIN_USER_ID


def test_connect_is_forbidden_for_a_signed_in_member_who_is_not_an_admin(client):
    response = client.get("/api/v1/mailbox/gmail/connect")
    assert response.status_code == 403


def test_callback_rejects_an_unknown_provider(client):
    response = client.get("/api/v1/mailbox/yahoo/callback", params={"code": "x", "state": "y"})
    assert response.status_code == 404


def test_callback_handles_the_user_declining_consent(client):
    response = client.get("/api/v1/mailbox/gmail/callback", params={"error": "access_denied"})
    assert response.status_code == 400
    assert "not completed" in response.text


def test_callback_rejects_a_missing_code_or_state(client):
    response = client.get("/api/v1/mailbox/gmail/callback", params={"state": "only-state"})
    assert response.status_code == 400


def test_callback_rejects_an_invalid_state(client):
    response = client.get("/api/v1/mailbox/gmail/callback", params={"code": "abc", "state": "not-a-real-token"})
    assert response.status_code == 400
    assert "expired or is invalid" in response.text


def test_callback_rejects_a_state_minted_for_a_different_provider(client):
    state = build_state(organization_id="acme", user_id=TEST_USER_ID, provider="outlook")
    response = client.get("/api/v1/mailbox/gmail/callback", params={"code": "abc", "state": state})
    assert response.status_code == 400


def test_callback_creates_a_connection_and_lists_it(client, monkeypatch):
    fake = FakeMailboxProvider(email_address="support@acme.com")
    monkeypatch.setattr("app.api.v1.endpoints.mailbox.build_provider", lambda provider: fake)

    state = build_state(organization_id="default", user_id=TEST_USER_ID, provider="gmail")
    callback_response = client.get("/api/v1/mailbox/gmail/callback", params={"code": "auth-code-1", "state": state})
    assert callback_response.status_code == 200
    assert "support@acme.com" in callback_response.text

    list_response = client.get("/api/v1/mailbox/connections")
    assert list_response.status_code == 200
    connections = list_response.json()["connections"]
    assert len(connections) == 1
    assert connections[0]["email_address"] == "support@acme.com"
    assert connections[0]["provider"] == "gmail"
    assert connections[0]["status"] == "active"


def test_disconnect_removes_a_connection_from_the_list(client, admin_client, monkeypatch):
    fake = FakeMailboxProvider(email_address="support@acme.com")
    monkeypatch.setattr("app.api.v1.endpoints.mailbox.build_provider", lambda provider: fake)
    state = build_state(organization_id="default", user_id=TEST_USER_ID, provider="gmail")
    client.get("/api/v1/mailbox/gmail/callback", params={"code": "auth-code-1", "state": state})
    connection_id = client.get("/api/v1/mailbox/connections").json()["connections"][0]["id"]

    delete_response = admin_client.delete(f"/api/v1/mailbox/connections/{connection_id}")
    assert delete_response.status_code == 204

    assert client.get("/api/v1/mailbox/connections").json()["connections"] == []


def test_disconnect_unknown_connection_returns_404(admin_client):
    response = admin_client.delete("/api/v1/mailbox/connections/00000000-0000-0000-0000-000000000099")
    assert response.status_code == 404


def test_disconnect_is_forbidden_for_a_signed_in_member_who_is_not_an_admin(client, admin_client, monkeypatch):
    fake = FakeMailboxProvider(email_address="support@acme.com")
    monkeypatch.setattr("app.api.v1.endpoints.mailbox.build_provider", lambda provider: fake)
    state = build_state(organization_id="default", user_id=TEST_USER_ID, provider="gmail")
    client.get("/api/v1/mailbox/gmail/callback", params={"code": "auth-code-1", "state": state})
    connection_id = client.get("/api/v1/mailbox/connections").json()["connections"][0]["id"]

    response = client.delete(f"/api/v1/mailbox/connections/{connection_id}")

    assert response.status_code == 403
    assert client.get("/api/v1/mailbox/connections").json()["connections"] != []
