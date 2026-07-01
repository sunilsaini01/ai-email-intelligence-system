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
