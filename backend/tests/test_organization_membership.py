"""
Security tests for organization membership (fix for unrestricted
registration into existing organizations).

Exercises the REAL auth flow end to end -- register, login, real bearer
tokens, no conftest auth overrides -- same stance as tests/test_auth.py,
since the point is proving the boundary itself holds.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 -- registers every table on Base.metadata
from app.core.security import hash_password
from app.database.session import Base, get_db
from app.main import create_app
from app.models.organization import Organization, OrganizationInvitation
from app.models.reply_draft import ReplyDraft
from app.models.user import (
    MEMBERSHIP_ADMIN_VERIFIED,
    MEMBERSHIP_INVITATION,
    MEMBERSHIP_LEGACY_UNVERIFIED,
    MEMBERSHIP_ORGANIZATION_CREATOR,
    ROLE_ADMIN,
    ROLE_AGENT,
    User,
)
from app.services.membership_service import (
    EmailAlreadyRegistered,
    InvalidInvitation,
    accept_invitation,
    issue_invitation,
)

PASSWORD = "correct-horse-battery"
VICTIM_ORG = "victim-org"


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


@pytest_asyncio.fixture
async def victim_org(session_factory):
    """An existing organization (pre-dating this fix, like real data)
    with an admin and a reply draft an outsider must never see."""
    async with session_factory() as s:
        s.add(Organization(id=VICTIM_ORG, name="Victim Inc"))
        s.add(User(email="boss@victim.com", hashed_password=hash_password(PASSWORD), organization_id=VICTIM_ORG,
                   role=ROLE_ADMIN, membership_source=MEMBERSHIP_ORGANIZATION_CREATOR))
        draft = ReplyDraft(organization_id=VICTIM_ORG, source_subject="Refund for ACME-42", source_body="secret",
                           generated_text="draft", generation_policy="NORMAL_REPLY")
        s.add(draft)
        await s.commit()
        return draft.id


def _register(client, email, organization_name="Outsider Ltd", **extra):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "organization_name": organization_name, **extra},
    )


def _token(client, email, password=PASSWORD):
    response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _invite(client, admin_token, email, role="agent", **extra):
    return client.post("/api/v1/admin/invitations", json={"email": email, "role": role, **extra},
                       headers=_auth(admin_token))


def _accept(client, token, email, password=PASSWORD):
    return client.post("/api/v1/auth/invitations/accept", json={"token": token, "email": email, "password": password})


async def _user_count(session_factory, **filters) -> int:
    async with session_factory() as s:
        query = select(func.count()).select_from(User)
        for field, value in filters.items():
            query = query.where(getattr(User, field) == value)
        return (await s.execute(query)).scalar_one()


# --- outsiders cannot join an existing organization ----------------------------


async def test_register_with_existing_organization_id_is_rejected(client, victim_org, session_factory):
    response = _register(client, "intruder@evil.com", organization_id=VICTIM_ORG)
    assert response.status_code == 422
    assert await _user_count(session_factory, email="intruder@evil.com") == 0
    assert await _user_count(session_factory, organization_id=VICTIM_ORG) == 1


async def test_rejected_signup_cannot_log_in_or_reach_organization_data(client, victim_org):
    _register(client, "intruder@evil.com", organization_id=VICTIM_ORG)
    login = client.post("/api/v1/auth/login", data={"username": "intruder@evil.com", "password": PASSWORD})
    assert login.status_code == 401
    assert client.get("/api/v1/reply").status_code == 401
    assert client.get(f"/api/v1/reply/{victim_org}").status_code == 401


async def test_signup_without_organization_id_does_not_join_default_or_any_existing_org(client, session_factory):
    async with session_factory() as s:
        s.add(Organization(id="default", name="default"))
        s.add(User(email="old@default.com", hashed_password="x", organization_id="default", role=ROLE_ADMIN))
        await s.commit()

    body = _register(client, "newcomer@example.com").json()
    assert body["organization_id"] not in ("default", VICTIM_ORG)
    assert body["organization_id"].startswith("org_")
    assert body["role"] == ROLE_ADMIN
    assert await _user_count(session_factory, organization_id="default") == 1


async def test_signup_using_an_existing_organizations_name_creates_a_separate_org(client, victim_org):
    body = _register(client, "copycat@evil.com", organization_name="Victim Inc").json()
    assert body["organization_id"] != VICTIM_ORG


async def test_outsider_new_org_admin_cannot_see_or_act_on_another_orgs_data(client, victim_org):
    _register(client, "intruder@evil.com")
    token = _token(client, "intruder@evil.com")
    listing = client.get("/api/v1/reply", headers=_auth(token))
    assert listing.status_code == 200 and listing.json()["drafts"] == []
    assert client.get(f"/api/v1/reply/{victim_org}", headers=_auth(token)).status_code == 404
    assert client.post(f"/api/v1/reply/{victim_org}/approve", json={}, headers=_auth(token)).status_code == 404
    assert client.post(f"/api/v1/reply/{victim_org}/reject", json={}, headers=_auth(token)).status_code == 404


async def test_public_signup_can_be_disabled(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ALLOW_PUBLIC_ORGANIZATION_SIGNUP", False)
    assert _register(client, "someone@example.com").status_code == 403


# --- invitation issuance is admin-only and scoped to the admin's org -----------


async def test_only_an_admin_can_issue_invitations(client, victim_org):
    admin = _token(client, "boss@victim.com")
    assert _accept(client, _invite(client, admin, "agent@victim.com").json()["token"], "agent@victim.com").status_code == 201
    assert _accept(client, _invite(client, admin, "mgr@victim.com", role="manager").json()["token"],
                   "mgr@victim.com").status_code == 201

    assert _invite(client, _token(client, "agent@victim.com"), "x@evil.com").status_code == 403
    assert _invite(client, _token(client, "mgr@victim.com"), "x@evil.com").status_code == 403
    assert client.post("/api/v1/admin/invitations", json={"email": "x@evil.com"}).status_code == 401


async def test_admin_cannot_target_another_organization(client, victim_org, session_factory):
    _register(client, "admin@other.com")
    other_admin = _token(client, "admin@other.com")

    assert _invite(client, other_admin, "mole@evil.com", organization_id=VICTIM_ORG).status_code == 422
    invited = _accept(client, _invite(client, other_admin, "mole@evil.com").json()["token"], "mole@evil.com").json()
    assert invited["organization_id"] != VICTIM_ORG


async def test_invitations_are_invisible_and_unrevokable_across_organizations(client, victim_org):
    victim_admin = _token(client, "boss@victim.com")
    invitation_id = _invite(client, victim_admin, "new@victim.com").json()["id"]

    _register(client, "admin@other.com")
    other_admin = _token(client, "admin@other.com")
    assert client.get("/api/v1/admin/invitations", headers=_auth(other_admin)).json()["invitations"] == []
    assert client.delete(f"/api/v1/admin/invitations/{invitation_id}", headers=_auth(other_admin)).status_code == 404
    statuses = [i["status"] for i in client.get("/api/v1/admin/invitations", headers=_auth(victim_admin)).json()["invitations"]]
    assert statuses == ["pending"]


async def test_inviting_an_already_registered_email_is_refused(client, victim_org):
    assert _invite(client, _token(client, "boss@victim.com"), "BOSS@victim.com").status_code == 409


# --- invitation validation ------------------------------------------------------


async def test_wrong_email_is_rejected_and_does_not_burn_the_invitation(client, victim_org, session_factory):
    token = _invite(client, _token(client, "boss@victim.com"), "invitee@victim.com").json()["token"]
    assert _accept(client, token, "intruder@evil.com").status_code == 400
    assert await _user_count(session_factory, email="intruder@evil.com") == 0
    accepted = _accept(client, token, "Invitee@Victim.com")  # email match is case-insensitive
    assert accepted.status_code == 201 and accepted.json()["organization_id"] == VICTIM_ORG


async def test_reused_invitation_is_rejected(client, victim_org, session_factory):
    token = _invite(client, _token(client, "boss@victim.com"), "invitee@victim.com").json()["token"]
    assert _accept(client, token, "invitee@victim.com").status_code == 201
    assert _accept(client, token, "invitee@victim.com", password="another-password").status_code == 400
    assert await _user_count(session_factory, email="invitee@victim.com") == 1


async def test_expired_invitation_is_rejected(client, victim_org, session_factory):
    token = _invite(client, _token(client, "boss@victim.com"), "late@victim.com").json()["token"]
    async with session_factory() as s:
        await s.execute(update(OrganizationInvitation).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        await s.commit()
    assert _accept(client, token, "late@victim.com").status_code == 400
    assert await _user_count(session_factory, email="late@victim.com") == 0


async def test_revoked_and_superseded_invitations_are_rejected(client, victim_org):
    admin = _token(client, "boss@victim.com")
    first = _invite(client, admin, "invitee@victim.com").json()
    second = _invite(client, admin, "invitee@victim.com").json()  # re-invite supersedes the first link
    assert _accept(client, first["token"], "invitee@victim.com").status_code == 400

    assert client.delete(f"/api/v1/admin/invitations/{second['id']}", headers=_auth(admin)).status_code == 204
    assert _accept(client, second["token"], "invitee@victim.com").status_code == 400


def test_unknown_token_is_rejected(client):
    assert _accept(client, "x" * 43, "anyone@example.com").status_code == 400


async def test_token_is_never_stored_or_listed(client, victim_org, session_factory):
    admin = _token(client, "boss@victim.com")
    created = _invite(client, admin, "invitee@victim.com").json()
    async with session_factory() as s:
        stored = (await s.execute(select(OrganizationInvitation.token_hash))).scalar_one()
    assert stored != created["token"] and len(stored) == 64
    assert "token" not in client.get("/api/v1/admin/invitations", headers=_auth(admin)).json()["invitations"][0]
    assert created["accept_path"] == f"/accept-invitation#token={created['token']}"


# --- concurrency ------------------------------------------------------------------


async def test_concurrent_acceptance_consumes_the_invitation_exactly_once(tmp_path):
    """Separate connections to one file database, racing the same token.
    The conditional UPDATE claim means exactly one acceptance succeeds;
    the loser gets InvalidInvitation (claim lost) or EmailAlreadyRegistered
    (claim won but user insert lost) -- never a second account."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}", connect_args={"timeout": 30})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with factory() as s:
        s.add(Organization(id=VICTIM_ORG, name="Victim Inc"))
        admin = User(email="boss@victim.com", hashed_password="x", organization_id=VICTIM_ORG, role=ROLE_ADMIN)
        s.add(admin)
        await s.commit()
        issued = await issue_invitation(s, admin, "invitee@victim.com", ROLE_AGENT)

    async def attempt():
        async with factory() as s:
            try:
                await accept_invitation(s, issued.token, "invitee@victim.com", "hash")
                return "ok"
            except (InvalidInvitation, EmailAlreadyRegistered):
                return "rejected"

    for _ in range(3):  # several rounds: interleavings vary run to run
        # Bounded: a regression in the claim condition can make the racers
        # contend on SQLite's lock indefinitely -- fail, don't hang CI.
        outcomes = await asyncio.wait_for(asyncio.gather(*(attempt() for _ in range(5))), timeout=60)
        assert outcomes.count("ok") <= 1
    async with factory() as s:
        users = (await s.execute(select(func.count()).select_from(User).where(User.email == "invitee@victim.com"))).scalar_one()
        accepted = (await s.execute(select(OrganizationInvitation.accepted_at))).scalar_one()
    assert users == 1 and accepted is not None
    await engine.dispose()


# --- legitimate membership ----------------------------------------------------------


async def test_creator_and_invitees_get_the_correct_membership_and_role(client, session_factory):
    founder = _register(client, "founder@new.com", organization_name="New Co").json()
    admin = _token(client, "founder@new.com")
    manager = _accept(client, _invite(client, admin, "lead@new.com", role="manager").json()["token"], "lead@new.com").json()
    assert manager["organization_id"] == founder["organization_id"] and manager["role"] == "manager"

    async with session_factory() as s:
        sources = dict((await s.execute(select(User.email, User.membership_source))).all())
        org = await s.get(Organization, founder["organization_id"])
    assert sources == {"founder@new.com": MEMBERSHIP_ORGANIZATION_CREATOR, "lead@new.com": MEMBERSHIP_INVITATION}
    assert org.name == "New Co" and str(org.created_by_user_id) == founder["id"]

    me = client.get("/api/v1/auth/me", headers=_auth(_token(client, "lead@new.com"))).json()
    assert me["role"] == "manager"


# --- existing protections still hold -------------------------------------------------


async def test_deactivated_user_cannot_log_in_and_token_stops_working(client, victim_org, session_factory):
    admin = _token(client, "boss@victim.com")
    _accept(client, _invite(client, admin, "leaver@victim.com").json()["token"], "leaver@victim.com")
    leaver_token = _token(client, "leaver@victim.com")
    async with session_factory() as s:
        await s.execute(update(User).where(User.email == "leaver@victim.com").values(is_active=False))
        await s.commit()
    assert client.get("/api/v1/auth/me", headers=_auth(leaver_token)).status_code == 401
    assert client.post("/api/v1/auth/login", data={"username": "leaver@victim.com", "password": PASSWORD}).status_code == 401


async def test_invited_member_sees_only_their_own_organizations_drafts(client, victim_org):
    admin = _token(client, "boss@victim.com")
    _accept(client, _invite(client, admin, "agent@victim.com").json()["token"], "agent@victim.com")
    drafts = client.get("/api/v1/reply", headers=_auth(_token(client, "agent@victim.com"))).json()["drafts"]
    assert [d["draft_id"] for d in drafts] == [str(victim_org)]


async def test_admin_can_review_and_confirm_legacy_accounts(client, victim_org, session_factory):
    async with session_factory() as s:
        legacy = User(email="legacy@victim.com", hashed_password="x", organization_id=VICTIM_ORG, role=ROLE_AGENT)
        s.add(legacy)
        await s.commit()
        legacy_id = legacy.id
    admin = _token(client, "boss@victim.com")
    users = {u["email"]: u for u in client.get("/api/v1/admin/users", headers=_auth(admin)).json()["users"]}
    assert users["legacy@victim.com"]["membership_source"] == MEMBERSHIP_LEGACY_UNVERIFIED
    assert users["legacy@victim.com"]["is_active"] is True  # never disabled automatically

    confirmed = client.patch(f"/api/v1/admin/users/{legacy_id}", json={"confirm_membership": True}, headers=_auth(admin))
    assert confirmed.json()["membership_source"] == MEMBERSHIP_ADMIN_VERIFIED


def test_audit_report_flags_unverified_multi_admin_and_odd_domains():
    from scripts.audit_organization_memberships import build_report

    now = datetime.now(UTC)
    users = [
        User(email="a@acme.com", organization_id="acme", role=ROLE_ADMIN, is_active=True,
             membership_source=MEMBERSHIP_LEGACY_UNVERIFIED, created_at=now),
        User(email="b@acme.com", organization_id="acme", role=ROLE_ADMIN, is_active=True,
             membership_source=MEMBERSHIP_ADMIN_VERIFIED, created_at=now),
        User(email="x@evil.com", organization_id="acme", role=ROLE_AGENT, is_active=True,
             membership_source=MEMBERSHIP_LEGACY_UNVERIFIED, created_at=now),
    ]
    report = "\n".join(build_report(users))
    assert "2 admins" in report and "2 unverified" in report
    assert "x@evil.com  <- domain differs from organization majority, UNVERIFIED" in report


# --- email identity (case variants) and transaction handling ------------------
# SQLite proves the application logic here; the PostgreSQL behavior
# (asyncpg constraint names, real concurrency) is proven separately in
# tests/test_membership_postgres_integration.py.


async def _insert_legacy_case_variants(session_factory):
    """Legacy state that predates uq_users_email_lower: drop the index
    first, exactly like a database still at revision a7e3d91c5b20."""
    from sqlalchemy import text

    async with session_factory() as s:
        await s.execute(text("DROP INDEX uq_users_email_lower"))
        s.add(Organization(id="other", name="Other"))
        s.add(User(email="Bob@x.com", hashed_password=hash_password("upper-password"), organization_id=VICTIM_ORG,
                   role=ROLE_ADMIN))
        s.add(User(email="bob@x.com", hashed_password=hash_password("lower-password"), organization_id="other",
                   role=ROLE_AGENT))
        await s.commit()


async def test_ambiguous_case_variant_login_fails_closed(client, victim_org, session_factory):
    await _insert_legacy_case_variants(session_factory)
    responses = [
        client.post("/api/v1/auth/login", data={"username": typed, "password": password})
        for typed in ("bob@x.com", "Bob@x.com", "BOB@X.COM")
        for password in ("upper-password", "lower-password")
    ]
    assert {r.status_code for r in responses} == {401}
    # Same body as an ordinary wrong password -- ambiguity isn't disclosed.
    wrong = client.post("/api/v1/auth/login", data={"username": "boss@victim.com", "password": "nope-nope"})
    assert {r.json()["detail"] for r in responses} == {wrong.json()["detail"]}


async def test_case_variant_of_existing_email_cannot_register_or_be_invited(client, victim_org, session_factory):
    assert _register(client, "BOSS@Victim.com").status_code == 409
    assert _invite(client, _token(client, "boss@victim.com"), "Boss@VICTIM.com").status_code == 409


async def test_database_rejects_case_variant_insert_directly(session_factory, victim_org):
    """The unique index on lower(email), not just the application check."""
    from sqlalchemy.exc import IntegrityError

    async with session_factory() as s:
        s.add(User(email="BOSS@victim.com", hashed_password="x", organization_id=VICTIM_ORG))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_email_registered_between_invite_and_accept_returns_409_and_keeps_invitation(
    client, victim_org, session_factory
):
    """Regression for the autoflush bug: the user INSERT used to fail inside
    a later execute(), outside the IntegrityError handler -> HTTP 500."""
    token = _invite(client, _token(client, "boss@victim.com"), "late@victim.com").json()["token"]
    async with session_factory() as s:  # registered by some other path meanwhile, different case
        s.add(User(email="LATE@victim.com", hashed_password="x", organization_id="elsewhere"))
        await s.commit()

    response = _accept(client, token, "late@victim.com")
    assert response.status_code == 409
    async with session_factory() as s:
        invitation = (await s.execute(select(OrganizationInvitation))).scalar_one()
    assert invitation.accepted_at is None and invitation.accepted_by_user_id is None


def test_only_email_uniqueness_violations_count_as_duplicate_email():
    from sqlalchemy.exc import IntegrityError

    from app.services.membership_service import is_duplicate_email_error

    class DriverError(Exception):
        def __init__(self, constraint_name=None, message=""):
            super().__init__(message)
            self.constraint_name = constraint_name

    def wrap(orig):
        return IntegrityError("INSERT ...", {}, orig)

    assert is_duplicate_email_error(wrap(DriverError("uq_users_email_lower")))
    assert is_duplicate_email_error(wrap(DriverError("ix_users_email")))
    assert not is_duplicate_email_error(wrap(DriverError("organizations_pkey")))
    assert not is_duplicate_email_error(wrap(DriverError(None, "NOT NULL constraint failed: users.role")))
    assert is_duplicate_email_error(wrap(DriverError(None, "UNIQUE constraint failed: users.email")))


async def test_unrelated_integrity_error_is_not_reported_as_duplicate_email(victim_org, session_factory):
    """A non-email constraint failure must propagate (-> 500), and the
    invitation must stay unconsumed."""
    from sqlalchemy.exc import IntegrityError

    from app.services import membership_service

    async with session_factory() as s:
        admin = (await s.execute(select(User).where(User.email == "boss@victim.com"))).scalar_one()
        issued = await issue_invitation(s, admin, "someone@victim.com", ROLE_AGENT)

    async with session_factory() as s:
        with pytest.raises(IntegrityError) as excinfo:
            # NULL hashed_password violates a NOT NULL constraint that has
            # nothing to do with email uniqueness.
            await accept_invitation(s, issued.token, "someone@victim.com", None)
        assert not membership_service.is_duplicate_email_error(excinfo.value)
    async with session_factory() as s:
        assert (await s.execute(select(OrganizationInvitation.accepted_at))).scalar_one() is None


def test_audit_report_lists_case_insensitive_collisions():
    from scripts.audit_organization_memberships import build_report, email_collisions

    now = datetime.now(UTC)
    users = [
        User(email="Bob@x.com", organization_id="a", role=ROLE_ADMIN, is_active=True,
             membership_source=MEMBERSHIP_LEGACY_UNVERIFIED, created_at=now),
        User(email="bob@x.com", organization_id="b", role=ROLE_AGENT, is_active=False,
             membership_source=MEMBERSHIP_LEGACY_UNVERIFIED, created_at=now),
        User(email="solo@x.com", organization_id="a", role=ROLE_AGENT, is_active=True,
             membership_source=MEMBERSHIP_ADMIN_VERIFIED, created_at=now),
    ]
    assert list(email_collisions(users)) == ["bob@x.com"]
    report = "\n".join(build_report(users))
    assert "1 email(s) shared by several accounts" in report
    assert "Bob@x.com" in report and "org=b role=agent inactive" in report
    assert "No case-insensitive email collisions." in "\n".join(build_report(users[2:]))
