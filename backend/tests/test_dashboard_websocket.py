"""
Dashboard live-update WebSocket (FR-54): authentication and tenant scoping.

Regression for a bug present since Phase 17: the socket sat under
protected_router, whose OAuth2PasswordBearer dependency needs an HTTP
Request -- every connection crashed with
`TypeError: OAuth2PasswordBearer.__call__() missing ... 'request'` and the
dashboard silently fell back to 30s polling. Events were also broadcast to
every connected dashboard regardless of organization.

Real auth flow (register -> login -> real token), no conftest overrides,
in-memory SQLite like tests/test_auth.py.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

import app.models  # noqa: F401
from app.database.session import Base, get_db
from app.main import create_app
from app.models.priority_prediction_log import PriorityPredictionLog
from app.models.user import User

PASSWORD = "correct-horse-battery"
WS_PATH = "/api/v1/dashboard/ws"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_db] = override_get_db
    return TestClient(application)


def _signup_and_token(client, email, organization_name):
    org = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD,
                                                     "organization_name": organization_name}).json()["organization_id"]
    token = client.post("/api/v1/auth/login", data={"username": email, "password": PASSWORD}).json()["access_token"]
    return org, token


async def _prediction_in(session_factory, organization_id):
    async with session_factory() as s:
        row = PriorityPredictionLog(organization_id=organization_id, body="b", predicted_priority="Low",
                                    confidence=0.2, model_version="v1", processing_ms=1.0)
        s.add(row)
        await s.commit()
        return row.id


def _confirm(client, token, prediction_id):
    response = client.post(
        f"/api/v1/dashboard/review-queue/{prediction_id}/confirm",
        json={"module": "priority", "subject": "s", "predicted_value": "Low", "confidence": 0.2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


def test_authenticated_socket_connects_and_negotiates_only_the_bearer_subprotocol(client):
    _, token = _signup_and_token(client, "a@acme.com", "Acme")
    with client.websocket_connect(WS_PATH, subprotocols=["bearer", token]) as ws:
        # The token itself is never echoed back as the accepted protocol.
        assert ws.accepted_subprotocol == "bearer"


@pytest.mark.parametrize("subprotocols", [None, ["bearer"], ["bearer", "not-a-jwt"], ["token", "x.y.z"]])
def test_socket_without_a_valid_token_is_rejected(client, subprotocols):
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(WS_PATH, subprotocols=subprotocols) as ws:
            ws.receive_text()
    assert excinfo.value.code == 1008


async def test_deactivated_user_cannot_open_the_socket(client, session_factory):
    _, token = _signup_and_token(client, "leaver@acme.com", "Acme")
    async with session_factory() as s:
        await s.execute(update(User).where(User.email == "leaver@acme.com").values(is_active=False))
        await s.commit()
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(WS_PATH, subprotocols=["bearer", token]) as ws:
            ws.receive_text()
    assert excinfo.value.code == 1008


async def test_events_are_delivered_only_to_the_events_organization(client, session_factory):
    acme_org, acme_token = _signup_and_token(client, "a@acme.com", "Acme")
    rival_org, rival_token = _signup_and_token(client, "r@rival.com", "Rival")
    acme_prediction = await _prediction_in(session_factory, acme_org)
    rival_prediction = await _prediction_in(session_factory, rival_org)

    with client.websocket_connect(WS_PATH, subprotocols=["bearer", acme_token]) as acme_ws, \
         client.websocket_connect(WS_PATH, subprotocols=["bearer", rival_token]) as rival_ws:
        _confirm(client, acme_token, acme_prediction)
        assert acme_ws.receive_json()["payload"]["prediction_id"] == str(acme_prediction)

        # If Acme's event had leaked to Rival, it would be the first message
        # Rival receives -- instead the first one is Rival's own.
        _confirm(client, rival_token, rival_prediction)
        assert rival_ws.receive_json()["payload"]["prediction_id"] == str(rival_prediction)

        # And the other way round: Acme's next message is its own new event,
        # not Rival's.
        second_acme_prediction = await _prediction_in(session_factory, acme_org)
        _confirm(client, acme_token, second_acme_prediction)
        assert acme_ws.receive_json()["payload"]["prediction_id"] == str(second_acme_prediction)
