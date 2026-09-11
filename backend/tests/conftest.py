"""
Shared pytest fixtures.

Why a TestClient fixture here instead of instantiating it per-test:
    Every test file would otherwise re-import and re-construct the app,
    which is wasteful and, more importantly, inconsistent if app construction
    ever needs setup/teardown logic (e.g. overriding DB dependency for tests).

Why `client` overrides get_current_user instead of every one of the 500+
pre-existing tests learning to register/login for a real token (Phase 17,
real authentication): those tests exist to exercise ML/business logic
(spam classification, routing, dashboard aggregation, ...), not the auth
layer itself -- making every one of them carry real login machinery
would be pure noise unrelated to what each test actually verifies.
FastAPI's own `app.dependency_overrides` mechanism is the standard,
first-class way to do this: it REPLACES get_current_user entirely for
requests made through this client, so no token, no DB user row, and no
Authorization header are needed by any test using this fixture. Tests
that need to verify the real auth flow itself (a login endpoint, an
unauthenticated request actually getting rejected) use `unauthenticated_client`
instead -- see tests/test_auth.py.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.auth_dependency import get_current_user
from app.main import create_app
from app.models.user import ROLE_MEMBER, User
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID

TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _fake_current_user() -> User:
    return User(
        id=TEST_USER_ID,
        email="test-fixture@example.com",
        hashed_password="unused",
        organization_id=DEFAULT_ORGANIZATION_ID,
        role=ROLE_MEMBER,
        is_active=True,
        created_at=datetime.now(UTC),
    )


def override_auth(app) -> None:
    """Shared helper for the several test files that build their OWN
    local `client` fixture (they also override get_db for an in-memory
    SQLite session, a pattern this fixture doesn't need) -- call this on
    that app instance too, so get_current_user is overridden consistently
    everywhere rather than copy-pasted per file. See test_dashboard_endpoint.py,
    test_reply_endpoint.py, and others for the call site."""
    app.dependency_overrides[get_current_user] = _fake_current_user


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    override_auth(app)
    return TestClient(app)


@pytest.fixture()
def unauthenticated_client() -> TestClient:
    """No auth override -- requests through this client carry no token,
    exactly like a real anonymous caller. For tests/test_auth.py and any
    test that needs to verify the real auth boundary, not bypass it."""
    app = create_app()
    return TestClient(app)
