"""
Tests the "model not trained yet" failure path (Module 11 / production
readiness). This must degrade to a clear, monitorable 503 — never a crash,
never a silent wrong prediction.
"""

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.spam as spam_endpoint
from app.services.spam_service import SpamService, SpamServiceUnavailable


def test_spam_service_raises_when_artifact_missing(tmp_path):
    with pytest.raises(SpamServiceUnavailable):
        SpamService(artifact_dir=str(tmp_path))


def test_endpoint_dependency_maps_unavailable_to_http_503(monkeypatch):
    def _raise_unavailable():
        raise SpamServiceUnavailable("no model trained yet")

    monkeypatch.setattr(spam_endpoint, "get_spam_service", _raise_unavailable)

    with pytest.raises(HTTPException) as exc_info:
        spam_endpoint._get_spam_service()

    assert exc_info.value.status_code == 503
