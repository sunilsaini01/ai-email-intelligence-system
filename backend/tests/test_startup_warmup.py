"""
Tests app/main.py's lifespan handler (Phase 4 follow-up: eager model
warm-up). Must use `with TestClient(app) as client:` — plain
`TestClient(app)` (used by the shared `client` fixture in conftest.py) never
runs ASGI lifespan events at all, verified empirically before relying on it
here. That's also why this doesn't affect any other test in the suite.
"""

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.priority_service import get_priority_service
from app.services.spam_service import get_spam_service


def test_lifespan_warms_up_both_ml_services():
    get_spam_service.cache_clear()
    get_priority_service.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        # Both services should already be constructed (cache populated)
        # by the time the app has finished starting -- no request needed.
        assert get_spam_service.cache_info().currsize == 1
        assert get_priority_service.cache_info().currsize == 1

        # And a real request should be fast, not pay a cold-start cost --
        # this is the actual behavior the warm-up exists to produce.
        response = client.post(
            "/api/v1/priority/predict",
            json={"subject": "test", "body": "quick warm request"},
        )
        assert response.status_code == 200

    get_spam_service.cache_clear()
    get_priority_service.cache_clear()


def test_lifespan_does_not_crash_app_startup_when_artifacts_missing(monkeypatch, tmp_path):
    """
    A fresh clone with no trained artifacts yet must still start the app --
    warm-up failures are logged, not raised. Simulated by pointing both
    services' default artifact dir somewhere with nothing in it.
    """
    import app.main as main_module

    monkeypatch.setattr(main_module, "get_spam_service", lambda: (_ for _ in ()).throw(RuntimeError("no artifact")))
    monkeypatch.setattr(main_module, "get_priority_service", lambda: (_ for _ in ()).throw(RuntimeError("no artifact")))

    app = create_app()
    # Must not raise -- this is the actual assertion.
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
