"""
Tests the "model not trained yet" failure path for email categorization,
mirroring test_priority_service_unavailable.py — same reasoning: must
degrade to a clear, monitorable 503, never a crash, never a silent wrong
prediction.
"""

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.category as category_endpoint
from app.services.category_service import CategoryService, CategoryServiceUnavailable


def test_category_service_raises_when_artifact_missing(tmp_path):
    with pytest.raises(CategoryServiceUnavailable):
        CategoryService(artifact_dir=str(tmp_path))


def test_endpoint_dependency_maps_unavailable_to_http_503(monkeypatch):
    def _raise_unavailable():
        raise CategoryServiceUnavailable("no model trained yet")

    monkeypatch.setattr(category_endpoint, "get_category_service", _raise_unavailable)

    with pytest.raises(HTTPException) as exc_info:
        category_endpoint._get_category_service()

    assert exc_info.value.status_code == 503
