"""
Shared pytest fixtures.

Why a TestClient fixture here instead of instantiating it per-test:
    Every test file would otherwise re-import and re-construct the app,
    which is wasteful and, more importantly, inconsistent if app construction
    ever needs setup/teardown logic (e.g. overriding DB dependency for tests).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    return TestClient(app)
