"""
Tests the "model not trained yet" failure path for intent detection,
mirroring test_category_service_unavailable.py.
"""

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.intent as intent_endpoint
from app.services.intent_service import IntentService, IntentServiceUnavailable


def test_intent_service_raises_when_artifact_missing(tmp_path):
    with pytest.raises(IntentServiceUnavailable):
        IntentService(artifact_dir=str(tmp_path))


def test_endpoint_dependency_maps_unavailable_to_http_503(monkeypatch):
    def _raise_unavailable():
        raise IntentServiceUnavailable("no model trained yet")

    monkeypatch.setattr(intent_endpoint, "get_intent_service", _raise_unavailable)

    with pytest.raises(HTTPException) as exc_info:
        intent_endpoint._get_intent_service()

    assert exc_info.value.status_code == 503
