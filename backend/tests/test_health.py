"""
Tests for the liveness endpoint.

Deliberately does NOT test /health/ready here — readiness depends on a live
Postgres connection, which isn't available in this unit test context.
Readiness gets covered by an integration test once docker-compose is up
(see tests/integration/, added in a later phase).
"""


def test_liveness_check_returns_200(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_liveness_check_response_shape(client):
    response = client.get("/api/v1/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "app_name" in body
    assert "environment" in body


def test_request_id_header_present(client):
    response = client.get("/api/v1/health")
    assert "X-Request-ID" in response.headers


def test_model_versions_returns_200(client):
    """GET /health/models (Phase 15A / FR-71 deployment identification)
    must stay available with zero MLflow/DB dependency -- a pure local-file
    read (see app/mlops/model_metadata.py)."""
    response = client.get("/api/v1/health/models")
    assert response.status_code == 200


def test_model_versions_reports_all_registrable_modules(client):
    from app.mlops.model_metadata import REGISTRABLE_MODULES

    body = client.get("/api/v1/health/models").json()
    reported_modules = {entry["module"] for entry in body["registered_models"]}
    assert reported_modules == set(REGISTRABLE_MODULES)


def test_model_versions_includes_non_registered_components(client):
    body = client.get("/api/v1/health/models").json()
    component_names = {entry["component_name"] for entry in body["other_components"]}
    assert "sentiment" in component_names
    assert "auto_reply_llm" in component_names
