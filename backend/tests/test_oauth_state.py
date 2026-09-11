"""Unit tests for app/ingestion/oauth_state.py (Phase 18)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.ingestion.oauth_state import (
    STATE_EXPIRE_MINUTES,
    InvalidOAuthState,
    build_state,
    verify_state,
)

USER_ID = uuid.uuid4()


def test_build_then_verify_round_trips_organization_and_user():
    state = build_state(organization_id="acme", user_id=USER_ID, provider="gmail")

    organization_id, user_id = verify_state(state, expected_provider="gmail")

    assert organization_id == "acme"
    assert user_id == USER_ID


def test_verify_rejects_a_state_issued_for_a_different_provider():
    state = build_state(organization_id="acme", user_id=USER_ID, provider="gmail")

    with pytest.raises(InvalidOAuthState):
        verify_state(state, expected_provider="outlook")


def test_verify_rejects_a_malformed_token():
    with pytest.raises(InvalidOAuthState):
        verify_state("not-a-real-jwt", expected_provider="gmail")


def test_verify_rejects_an_expired_state():
    settings = get_settings()
    now = datetime.now(UTC)
    expired_payload = {
        "org": "acme",
        "user_id": str(USER_ID),
        "provider": "gmail",
        "type": "mailbox_oauth_state",
        "iat": now - timedelta(minutes=STATE_EXPIRE_MINUTES + 5),
        "exp": now - timedelta(minutes=5),
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(InvalidOAuthState):
        verify_state(expired_token, expected_provider="gmail")


def test_verify_rejects_a_token_of_the_wrong_type():
    """A login access token (app/core/security.py) must not be usable as
    mailbox OAuth state, even if signed with the same SECRET_KEY."""
    from app.core.security import create_access_token

    login_token = create_access_token(subject=str(USER_ID), organization_id="acme", role="member")

    with pytest.raises(InvalidOAuthState):
        verify_state(login_token, expected_provider="gmail")
