"""
Tests the "model not trained yet" failure path for priority classification,
mirroring test_spam_service_unavailable.py — same reasoning: must degrade to
a clear, monitorable 503, never a crash, never a silent wrong prediction.
"""

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.priority as priority_endpoint
from app.services.priority_service import PriorityService, PriorityServiceUnavailable


def test_priority_service_raises_when_artifact_missing(tmp_path):
    with pytest.raises(PriorityServiceUnavailable):
        PriorityService(artifact_dir=str(tmp_path))


def test_endpoint_dependency_maps_unavailable_to_http_503(monkeypatch):
    def _raise_unavailable():
        raise PriorityServiceUnavailable("no model trained yet")

    monkeypatch.setattr(priority_endpoint, "get_priority_service", _raise_unavailable)

    with pytest.raises(HTTPException) as exc_info:
        priority_endpoint._get_priority_service()

    assert exc_info.value.status_code == 503
