"""
Real-PostgreSQL integration tests for organization membership.

tests/test_organization_membership.py covers the application logic on
SQLite. SQLite is not PostgreSQL: it serializes writers with a file lock,
reports constraint violations differently and has no row-level locking.
This file proves the security properties on a real PostgreSQL server,
against a schema built by the Alembic migrations (never
Base.metadata.create_all):

  - concurrent acceptance of one invitation creates exactly one user;
  - a failed user insert rolls the invitation claim back;
  - expired / revoked / reused / wrong-email / cross-tenant attempts fail;
  - organization + creator-admin creation is atomic, including under a
    concurrent case-variant signup;
  - case-insensitive email uniqueness is enforced by the database;
  - migrations: fresh database, upgrade/downgrade round trip, and an
    upgrade from the last pre-fix revision with representative legacy
    data (with and without case-variant email collisions).

ISOLATION / SAFETY. Opt-in: skipped unless EIS_TEST_POSTGRES_ADMIN_URL
points at a server the tests may create databases on, e.g.

    EIS_TEST_POSTGRES_ADMIN_URL=postgresql://postgres:postgres@localhost:5432/postgres

Every test works in its OWN throwaway database named `eis_it_<random>`
(created from a migrated template, or migrated itself), and the only
destructive statement this file ever issues is DROP DATABASE on a name it
generated and which starts with that prefix. No existing database is
touched, migrated or cleaned. Point it at a disposable server anyway
(the CI service container, or a local `initdb` cluster).

Coordination: races are made deterministic by holding a row/index lock
in one session, waiting (bounded) until the competing sessions are
visibly blocked on it in pg_stat_activity, then releasing it. Every wait
is bounded with asyncio.wait_for / subprocess timeouts so a regression
fails instead of hanging.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ADMIN_URL_ENV = "EIS_TEST_POSTGRES_ADMIN_URL"
DB_PREFIX = "eis_it_"
BACKEND_DIR = Path(__file__).resolve().parents[1]
HEAD = "c5b1e8f2a4d6"
PRE_FIX_REVISION = "e8b2f4a91c73"  # last revision before Phase 22 / the membership fix
LOCK_WAIT_TIMEOUT = 20
RACE_TIMEOUT = 60

pytestmark = pytest.mark.skipif(
    not os.environ.get(ADMIN_URL_ENV),
    reason=f"Real-PostgreSQL integration tests: set {ADMIN_URL_ENV} to a disposable server's admin URL "
    "(see this module's docstring).",
)


# --- isolated database management ----------------------------------------------


def _admin_url():
    return make_url(os.environ[ADMIN_URL_ENV])


def _asyncpg_dsn(database: str) -> str:
    url = _admin_url().set(drivername="postgresql", database=database)
    return url.render_as_string(hide_password=False)


def _sqlalchemy_url(database: str) -> str:
    url = _admin_url().set(drivername="postgresql+asyncpg", database=database)
    return url.render_as_string(hide_password=False)


def _run_admin(*statements: str) -> None:
    import asyncpg

    async def run():
        conn = await asyncpg.connect(_asyncpg_dsn(_admin_url().database or "postgres"), timeout=10)
        try:
            for statement in statements:
                await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(run())


def _create_database(template: str | None = None) -> str:
    name = f"{DB_PREFIX}{uuid.uuid4().hex[:12]}"
    _run_admin(f'CREATE DATABASE "{name}"' + (f' TEMPLATE "{template}"' if template else ""))
    return name


def _drop_database(name: str) -> None:
    # The ONLY destructive statement in this file -- refuses anything this
    # module did not generate.
    assert name.startswith(DB_PREFIX) and name[len(DB_PREFIX):].isalnum(), name
    _run_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _alembic(database: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Runs Alembic in a subprocess pointed at `database` -- the app's
    settings are lru_cache'd at import, so they can't be re-pointed in
    this process (see tests/test_phase12_kafka_integration.py)."""
    url = _admin_url()
    env = {
        **os.environ,
        "POSTGRES_HOST": url.host or "localhost",
        "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_USER": url.username or "postgres",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_DB": database,
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result


@pytest.fixture(scope="module")
def migrated_template():
    """One database migrated to head through Alembic; each test gets a
    copy (CREATE DATABASE ... TEMPLATE) instead of re-running Alembic."""
    name = _create_database()
    try:
        _alembic(name, "upgrade", "head")
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def pg_db(migrated_template):
    name = _create_database(template=migrated_template)
    try:
        yield name
    finally:
        _drop_database(name)


def _engine(database: str):
    # NullPool: no connection outlives the test's event loop.
    return create_async_engine(_sqlalchemy_url(database), poolclass=NullPool)


async def _wait_for_lock_waiters(engine, count: int) -> None:
    """Bounded wait until `count` other backends in this database are
    blocked waiting on a lock."""

    async def poll():
        while True:
            async with engine.connect() as conn:
                waiting = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                        )
                    )
                ).scalar_one()
            if waiting >= count:
                return
            await asyncio.sleep(0.05)

    await asyncio.wait_for(poll(), timeout=LOCK_WAIT_TIMEOUT)


# --- seed helpers -------------------------------------------------------------


async def _seed_org_with_admin(factory, org_id="acme", email="boss@acme.com"):
    from app.models.organization import Organization
    from app.models.user import MEMBERSHIP_ORGANIZATION_CREATOR, ROLE_ADMIN, User

    async with factory() as s:
        s.add(Organization(id=org_id, name=org_id))
        admin = User(email=email, hashed_password="x", organization_id=org_id, role=ROLE_ADMIN,
                     membership_source=MEMBERSHIP_ORGANIZATION_CREATOR)
        s.add(admin)
        await s.commit()
        return admin


async def _count(factory, statement) -> int:
    async with factory() as s:
        return (await s.execute(statement)).scalar_one()


# --- invitation acceptance --------------------------------------------------------


async def test_concurrent_acceptance_creates_exactly_one_user(pg_db):
    from app.models.organization import OrganizationInvitation
    from app.models.user import ROLE_AGENT, User
    from app.services.membership_service import (
        EmailAlreadyRegistered,
        InvalidInvitation,
        accept_invitation,
        hash_invitation_token,
        issue_invitation,
    )

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        admin = await _seed_org_with_admin(factory)
        async with factory() as s:
            issued = await issue_invitation(s, admin, "invitee@acme.com", ROLE_AGENT)

        racers = 4
        async with factory() as gate:
            # Hold the invitation row so every racer queues behind it ...
            await gate.execute(
                select(OrganizationInvitation.id)
                .where(OrganizationInvitation.token_hash == hash_invitation_token(issued.token))
                .with_for_update()
            )

            async def attempt():
                async with factory() as s:
                    try:
                        await accept_invitation(s, issued.token, "invitee@acme.com", "hash")
                        return "accepted"
                    except InvalidInvitation:
                        return "invalid"
                    except EmailAlreadyRegistered:
                        return "duplicate"

            tasks = [asyncio.create_task(attempt()) for _ in range(racers)]
            # ... prove they are all genuinely concurrent (blocked on it) ...
            await _wait_for_lock_waiters(engine, racers)
            # ... then release them at once.
            await gate.rollback()
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), timeout=RACE_TIMEOUT)

        assert outcomes.count("accepted") == 1, outcomes
        # Losers re-check the claim's WHERE clause after the winner commits
        # and see accepted_at set: rejected at the claim, not at the insert.
        assert outcomes.count("invalid") == racers - 1, outcomes
        assert await _count(factory, select(func.count()).select_from(User).where(User.email == "invitee@acme.com")) == 1
        async with factory() as s:
            invitation = (await s.execute(select(OrganizationInvitation))).scalar_one()
        assert invitation.accepted_at is not None and invitation.accepted_by_user_id is not None
    finally:
        await engine.dispose()


async def test_failed_user_creation_rolls_back_invitation_consumption(pg_db):
    from app.models.organization import OrganizationInvitation
    from app.models.user import ROLE_AGENT, User
    from app.services.membership_service import (
        EmailAlreadyRegistered,
        accept_invitation,
        issue_invitation,
    )

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        admin = await _seed_org_with_admin(factory)
        async with factory() as s:
            issued = await issue_invitation(s, admin, "late@acme.com", ROLE_AGENT)
        async with factory() as s:  # registered elsewhere after the invitation, different case
            s.add(User(email="LATE@acme.com", hashed_password="x", organization_id="elsewhere"))
            await s.commit()

        async with factory() as s:
            # asyncpg reports the violated constraint by name; this must be
            # recognized as a duplicate email, not escape as a raw error.
            with pytest.raises(EmailAlreadyRegistered):
                await accept_invitation(s, issued.token, "late@acme.com", "hash")

        async with factory() as s:
            invitation = (await s.execute(select(OrganizationInvitation))).scalar_one()
        assert invitation.accepted_at is None and invitation.accepted_by_user_id is None
        assert await _count(factory, select(func.count()).select_from(User).where(func.lower(User.email) == "late@acme.com")) == 1
    finally:
        await engine.dispose()


async def test_non_email_constraint_failure_is_not_reported_as_duplicate_and_rolls_back(pg_db):
    from app.models.organization import OrganizationInvitation
    from app.models.user import ROLE_AGENT
    from app.services.membership_service import (
        accept_invitation,
        is_duplicate_email_error,
        issue_invitation,
    )

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        admin = await _seed_org_with_admin(factory)
        async with factory() as s:
            issued = await issue_invitation(s, admin, "x@acme.com", ROLE_AGENT)
        async with factory() as s:
            with pytest.raises(IntegrityError) as excinfo:
                await accept_invitation(s, issued.token, "x@acme.com", None)  # NOT NULL hashed_password
        assert not is_duplicate_email_error(excinfo.value)
        async with factory() as s:
            assert (await s.execute(select(OrganizationInvitation.accepted_at))).scalar_one() is None
    finally:
        await engine.dispose()


async def test_expired_revoked_reused_wrong_email_and_cross_tenant_attempts_fail(pg_db):
    from app.models.organization import OrganizationInvitation
    from app.models.user import ROLE_AGENT, User
    from app.services.membership_service import (
        InvalidInvitation,
        accept_invitation,
        issue_invitation,
        revoke_invitation,
    )

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        acme_admin = await _seed_org_with_admin(factory, "acme", "boss@acme.com")
        await _seed_org_with_admin(factory, "rival", "boss@rival.com")

        async def issue(email):
            async with factory() as s:
                return await issue_invitation(s, acme_admin, email, ROLE_AGENT)

        async def accept(token, email):
            async with factory() as s:
                return await accept_invitation(s, token, email, "hash")

        # wrong email -- and the right email still works afterwards
        wrong = await issue("right@acme.com")
        with pytest.raises(InvalidInvitation):
            await accept(wrong.token, "intruder@evil.com")
        assert (await accept(wrong.token, "right@acme.com")).organization_id == "acme"

        # reused
        with pytest.raises(InvalidInvitation):
            await accept(wrong.token, "right@acme.com")

        # expired
        expired = await issue("late@acme.com")
        async with factory() as s:
            await s.execute(
                update(OrganizationInvitation)
                .where(OrganizationInvitation.id == expired.invitation.id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await s.commit()
        with pytest.raises(InvalidInvitation):
            await accept(expired.token, "late@acme.com")

        # revoked
        revoked = await issue("gone@acme.com")
        async with factory() as s:
            assert await revoke_invitation(s, "acme", revoked.invitation.id)
        with pytest.raises(InvalidInvitation):
            await accept(revoked.token, "gone@acme.com")

        # cross-tenant: another org's admin cannot revoke it, and accepting
        # always lands in the issuing organization
        target = await issue("new@acme.com")
        async with factory() as s:
            assert not await revoke_invitation(s, "rival", target.invitation.id)
        assert (await accept(target.token, "new@acme.com")).organization_id == "acme"

        emails = {
            e for (e,) in (await _all(factory, select(User.email).where(User.organization_id == "acme")))
        }
        assert emails == {"boss@acme.com", "right@acme.com", "new@acme.com"}
    finally:
        await engine.dispose()


async def _all(factory, statement):
    async with factory() as s:
        return (await s.execute(statement)).all()


# --- organization creation / email uniqueness -----------------------------------


async def test_organization_creation_is_atomic_with_its_admin_under_a_racing_case_variant(pg_db):
    from app.models.organization import Organization
    from app.models.user import User
    from app.services.membership_service import (
        EmailAlreadyRegistered,
        create_organization_with_admin,
    )

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with factory() as holder:
            # A concurrent signup has inserted "Dup@X.com" but not committed.
            holder.add(User(email="Dup@X.com", hashed_password="x", organization_id="holder"))
            await holder.flush()

            async def signup():
                async with factory() as s:
                    return await create_organization_with_admin(s, "Racer", "dup@x.com", "hash")

            # Its pre-check can't see the uncommitted row, so it reaches the
            # INSERT and blocks on the lower(email) unique index ...
            task = asyncio.create_task(signup())
            await _wait_for_lock_waiters(engine, 1)
            await holder.commit()
        # ... and fails cleanly once the holder commits.
        with pytest.raises(EmailAlreadyRegistered):
            await asyncio.wait_for(task, timeout=RACE_TIMEOUT)

        # The organization row it inserted in the same transaction is gone.
        assert await _count(factory, select(func.count()).select_from(Organization)) == 0
        assert await _count(factory, select(func.count()).select_from(User)) == 1
    finally:
        await engine.dispose()


async def test_concurrent_case_variant_signups_create_exactly_one_account(pg_db):
    from app.models.organization import Organization
    from app.models.user import ROLE_ADMIN, User
    from app.services.membership_service import (
        EmailAlreadyRegistered,
        create_organization_with_admin,
    )

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        variants = ["same@x.com", "SAME@x.com", "Same@X.com", "same@X.COM", "sAmE@x.com"]

        async def signup(email):
            async with factory() as s:
                try:
                    await create_organization_with_admin(s, f"Org {email}", email, "hash")
                    return "created"
                except EmailAlreadyRegistered:
                    return "duplicate"

        outcomes = await asyncio.wait_for(asyncio.gather(*(signup(e) for e in variants)), timeout=RACE_TIMEOUT)
        assert outcomes.count("created") == 1, outcomes
        assert outcomes.count("duplicate") == len(variants) - 1, outcomes
        rows = await _all(factory, select(User.email, User.role, User.organization_id))
        assert len(rows) == 1 and rows[0].role == ROLE_ADMIN and rows[0].email == "same@x.com"
        orgs = await _all(factory, select(Organization.id, Organization.created_by_user_id))
        assert len(orgs) == 1 and orgs[0].id == rows[0].organization_id
    finally:
        await engine.dispose()


async def test_database_enforces_case_insensitive_email_uniqueness(pg_db):
    from app.models.user import User

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with factory() as s:
            s.add(User(email="Ann@x.com", hashed_password="x", organization_id="a"))
            await s.commit()
        async with factory() as s:
            s.add(User(email="ann@X.com", hashed_password="x", organization_id="b"))
            with pytest.raises(IntegrityError) as excinfo:
                await s.commit()
        assert "uq_users_email_lower" in str(excinfo.value)
    finally:
        await engine.dispose()


def test_http_flow_on_postgres(pg_db):
    """Signup, invitation, acceptance, login, reuse, revocation and
    cross-tenant denial through the real API, on the migrated schema."""
    from fastapi.testclient import TestClient

    from app.database.session import get_db
    from app.main import create_app

    engine = _engine(pg_db)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_db] = override_get_db
    client = TestClient(application)
    password = "correct-horse-battery"

    def token(email):
        response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    founder = client.post("/api/v1/auth/register", json={"email": "Founder@Acme.com", "password": password,
                                                         "organization_name": "Acme"})
    assert founder.status_code == 201 and founder.json()["role"] == "admin"
    acme = founder.json()["organization_id"]
    assert client.post("/api/v1/auth/register", json={"email": "x@evil.com", "password": password,
                                                      "organization_name": "E", "organization_id": acme}).status_code == 422
    assert client.post("/api/v1/auth/register", json={"email": "founder@ACME.com", "password": password,
                                                      "organization_name": "Again"}).status_code == 409

    admin = token("founder@acme.com")
    invitation = client.post("/api/v1/admin/invitations", json={"email": "agent@acme.com"}, headers=admin).json()
    accept = {"token": invitation["token"], "email": "agent@acme.com", "password": password}
    joined = client.post("/api/v1/auth/invitations/accept", json=accept)
    assert joined.status_code == 201 and joined.json()["organization_id"] == acme
    assert client.post("/api/v1/auth/invitations/accept", json=accept).status_code == 400  # reuse
    assert client.get("/api/v1/auth/me", headers=token("AGENT@acme.com")).json()["role"] == "agent"

    revoked = client.post("/api/v1/admin/invitations", json={"email": "never@acme.com"}, headers=admin).json()
    assert client.delete(f"/api/v1/admin/invitations/{revoked['id']}", headers=admin).status_code == 204
    assert client.post("/api/v1/auth/invitations/accept",
                       json={"token": revoked["token"], "email": "never@acme.com", "password": password}).status_code == 400

    client.post("/api/v1/auth/register", json={"email": "boss@rival.com", "password": password, "organization_name": "Rival"})
    rival = token("boss@rival.com")
    pending = client.post("/api/v1/admin/invitations", json={"email": "p@acme.com"}, headers=admin).json()
    assert client.get("/api/v1/admin/invitations", headers=rival).json()["invitations"] == []
    assert client.delete(f"/api/v1/admin/invitations/{pending['id']}", headers=rival).status_code == 404
    assert client.get("/api/v1/admin/users", headers=rival).json()["users"][0]["email"] == "boss@rival.com"
    assert len(client.get("/api/v1/admin/users", headers=rival).json()["users"]) == 1
    asyncio.run(engine.dispose())


# --- migrations -----------------------------------------------------------------


def _query(database: str, sql: str, *args):
    import asyncpg

    async def run():
        conn = await asyncpg.connect(_asyncpg_dsn(database), timeout=10)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def _execute(database: str, sql: str) -> None:
    import asyncpg

    async def run():
        conn = await asyncpg.connect(_asyncpg_dsn(database), timeout=10)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(run())


def test_fresh_database_migrates_round_trips_and_has_the_constraints():
    name = _create_database()
    try:
        _alembic(name, "upgrade", "head")
        _alembic(name, "downgrade", "base")
        _alembic(name, "upgrade", "head")
        assert _query(name, "SELECT version_num FROM alembic_version")[0]["version_num"] == HEAD
        indexes = {r["indexname"] for r in _query(name, "SELECT indexname FROM pg_indexes WHERE tablename = 'users'")}
        assert {"ix_users_email", "uq_users_email_lower"} <= indexes
        tables = {r["tablename"] for r in _query(name, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
        assert {"organizations", "organization_invitations"} <= tables
    finally:
        _drop_database(name)


_LEGACY_USERS = [
    # id, email, organization_id, role, is_active
    ("11111111-1111-1111-1111-111111111111", "founder@acme.com", "acme", "admin", True),
    ("22222222-2222-2222-2222-222222222222", "Agent@Acme.com", "acme", "member", True),
    ("33333333-3333-3333-3333-333333333333", "former@acme.com", "acme", "member", False),
    ("44444444-4444-4444-4444-444444444444", "walkin@example.com", "default", "member", True),
    ("55555555-5555-5555-5555-555555555555", "solo@widgets.io", "widgets", "admin", True),
]


def _seed_legacy(database: str, users) -> None:
    values = ", ".join(
        f"('{uid}', '{email}', 'legacy-hash', '{org}', '{role}', {str(active).lower()})"
        for uid, email, org, role, active in users
    )
    _execute(database, f"INSERT INTO users (id, email, hashed_password, organization_id, role, is_active) VALUES {values}")
    _execute(database, "INSERT INTO emails (organization_id, content_hash, subject, body) VALUES "
                       "('acme', 'h1', 's', 'b'), ('default', 'h2', 's', 'b')")


def test_upgrade_from_pre_fix_revision_preserves_legacy_accounts():
    name = _create_database()
    try:
        _alembic(name, "upgrade", PRE_FIX_REVISION)
        _seed_legacy(name, _LEGACY_USERS)
        _alembic(name, "upgrade", "head")

        rows = {str(r["id"]): r for r in _query(
            name, "SELECT id, email, organization_id, role, is_active, membership_source, hashed_password FROM users")}
        assert len(rows) == len(_LEGACY_USERS)
        expected_role = {"admin": "admin", "member": "agent"}  # Phase 22: member renamed to agent
        for uid, email, org, role, active in _LEGACY_USERS:
            row = rows[uid]
            assert (row["email"], row["organization_id"], row["is_active"]) == (email, org, active)
            assert row["role"] == expected_role[role]
            assert row["hashed_password"] == "legacy-hash"
            # Flagged for review -- never confirmed, disabled or modified otherwise.
            assert row["membership_source"] == "legacy_unverified"

        orgs = {r["id"] for r in _query(name, "SELECT id FROM organizations")}
        assert orgs == {"acme", "default", "widgets"}
        assert {r["organization_id"] for r in _query(name, "SELECT organization_id FROM emails")} == {"acme", "default"}
        assert _query(name, "SELECT version_num FROM alembic_version")[0]["version_num"] == HEAD
    finally:
        _drop_database(name)


def test_upgrade_refuses_while_case_variant_collisions_exist_then_succeeds_once_resolved():
    name = _create_database()
    collision = [
        ("66666666-6666-6666-6666-666666666666", "Bob@X.com", "acme", "admin", True),
        ("77777777-7777-7777-7777-777777777777", "bob@x.com", "widgets", "member", True),
    ]
    try:
        _alembic(name, "upgrade", PRE_FIX_REVISION)
        _seed_legacy(name, _LEGACY_USERS + collision)

        refused = _alembic(name, "upgrade", "head", check=False)
        assert refused.returncode != 0
        output = refused.stdout + refused.stderr
        assert "Cannot create uq_users_email_lower" in output
        assert "bob@x.com (2 accounts)" in output
        assert all(uid in output for uid, *_ in collision)
        # One transaction for the whole upgrade: nothing from it was applied.
        assert _query(name, "SELECT version_num FROM alembic_version")[0]["version_num"] == PRE_FIX_REVISION
        assert {r["role"] for r in _query(name, "SELECT role FROM users")} == {"admin", "member"}

        # Staged deploy: the membership fix itself still applies.
        _alembic(name, "upgrade", "a7e3d91c5b20")

        # The read-only audit names the collision and changes nothing.
        before = _query(name, "SELECT id, email, is_active, role, membership_source FROM users ORDER BY id")
        audit = _run_audit(name)
        assert "1 email(s) shared by several accounts" in audit and "Bob@X.com" in audit and "bob@x.com" in audit
        assert _query(name, "SELECT id, email, is_active, role, membership_source FROM users ORDER BY id") == before

        # Operator resolution (a human decision, simulated): the second
        # account's address is changed to the person's real one.
        _execute(name, "UPDATE users SET email = 'robert@widgets.io' WHERE id = '77777777-7777-7777-7777-777777777777'")
        _alembic(name, "upgrade", "head")
        assert _query(name, "SELECT version_num FROM alembic_version")[0]["version_num"] == HEAD
    finally:
        _drop_database(name)


def _run_audit(database: str) -> str:
    url = _admin_url()
    env = {
        **os.environ,
        "POSTGRES_HOST": url.host or "localhost",
        "POSTGRES_PORT": str(url.port or 5432),
        "POSTGRES_USER": url.username or "postgres",
        "POSTGRES_PASSWORD": url.password or "",
        "POSTGRES_DB": database,
        "LOG_LEVEL": "WARNING",
    }
    result = subprocess.run(
        [sys.executable, "-m", "scripts.audit_organization_memberships"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout
