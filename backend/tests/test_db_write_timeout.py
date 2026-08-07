"""
Regression test for the DB-write-hang bug found while verifying the startup
warm-up fix (see docs/architecture_priority_classification.md): a *hanging*
DB connection attempt (as opposed to one that raises quickly) used to block
the response indefinitely, because the endpoints' try/except only catches
raised exceptions. Both endpoints now wrap the write in
asyncio.wait_for(DB_WRITE_TIMEOUT_SECONDS) - this proves that actually
bounds the wait, using a fake session whose commit() never completes on its
own, rather than depending on a real (and here, unreliable) Postgres
connection to reproduce the hang.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import app.api.v1.endpoints.priority as priority_endpoint
import app.api.v1.endpoints.spam as spam_endpoint
from app.database.session import get_db
from app.main import create_app
from app.services.priority_service import get_priority_service
from app.services.spam_service import get_spam_service


class _HangingSession:
    """Stands in for an AsyncSession whose commit() never returns on its
    own — simulates the observed hanging-connection failure mode without
    depending on a real, unreliable DB connection to reproduce it."""

    def add(self, record):
        pass

    async def commit(self):
        await asyncio.sleep(999)

    async def refresh(self, record):
        pass


@pytest.fixture
def hanging_db_client():
    # Deliberately does NOT clear the service caches: this test measures
    # whether the DB write specifically is time-bounded, not cold-start
    # model-loading time (spaCy's lazy load alone adds ~1s the first time -
    # see docs/architecture_priority_classification.md "Performance" - which
    # would swamp the sub-second bound this test is actually checking for
    # and has nothing to do with the bug being guarded against).
    async def override_get_db():
        yield _HangingSession()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    # Warm both services up before timing anything, same reasoning.
    get_spam_service()
    get_priority_service()

    yield TestClient(app)

    app.dependency_overrides.clear()


def test_spam_predict_does_not_hang_when_db_write_hangs(hanging_db_client, monkeypatch):
    monkeypatch.setattr(spam_endpoint, "DB_WRITE_TIMEOUT_SECONDS", 0.2)

    start = time.perf_counter()
    response = hanging_db_client.post(
        "/api/v1/spam/predict",
        json={"subject": "test", "body": "does this hang the request"},
    )
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed < 3.0, f"request took {elapsed:.1f}s -- the timeout did not bound the hang"


def test_priority_predict_does_not_hang_when_db_write_hangs(hanging_db_client, monkeypatch):
    monkeypatch.setattr(priority_endpoint, "DB_WRITE_TIMEOUT_SECONDS", 0.2)

    start = time.perf_counter()
    response = hanging_db_client.post(
        "/api/v1/priority/predict",
        json={"subject": "test", "body": "does this hang the request"},
    )
    elapsed = time.perf_counter() - start

    assert response.status_code == 200
    assert elapsed < 3.0, f"request took {elapsed:.1f}s -- the timeout did not bound the hang"
