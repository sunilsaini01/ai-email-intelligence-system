"""
Integration tests for the retrieval endpoints (Module 9 / Phase 9).

Uses a real `TfidfEmbedder` (skipped if its artifact doesn't exist -- same
convention as every other module's real-artifact-gated integration test)
and a real `ChromaVectorStore`, but pointed at a fresh `tmp_path` --
NEVER the real `artifacts/chroma/` directory a running application would
use. DB uses the same in-memory-SQLite-plus-dependency-override pattern
every other module's DB-touching endpoint test uses.
"""

from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.session import Base, get_db
from app.inference.tfidf_embedder import _DEFAULT_ARTIFACT_DIR
from app.main import create_app
from app.retrieval.chroma_vector_store import ChromaVectorStore
from app.services.retrieval_service import RetrievalService, get_retrieval_service

pytestmark = pytest.mark.skipif(
    not (Path(_DEFAULT_ARTIFACT_DIR) / "tfidf_embedder.joblib").exists(),
    reason="tfidf_embedder.joblib not found -- run scripts/train_tfidf_embedder.py first",
)


@pytest_asyncio.fixture
async def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.fixture
def retrieval_client(sqlite_session_factory, tmp_path):
    get_retrieval_service.cache_clear()
    fake_service = RetrievalService(vector_store=ChromaVectorStore(persist_dir=str(tmp_path / "chroma")))

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_retrieval_service] = lambda: fake_service

    yield TestClient(app)

    app.dependency_overrides.clear()
    get_retrieval_service.cache_clear()


def test_index_returns_a_structurally_valid_response(retrieval_client):
    response = retrieval_client.post(
        "/api/v1/retrieval/index",
        json={"subject": "Refund", "body": "I want a refund for my payment.", "category": "Billing", "department": "Billing"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["was_created"] is True
    assert body["index_status"] == "INDEXED"
    assert body["embedding_dimension"] > 0
    assert body["processing_ms"] >= 0


def test_index_is_idempotent(retrieval_client):
    payload = {"subject": "Refund", "body": "I want a refund for my payment.", "category": "Billing", "department": "Billing"}
    r1 = retrieval_client.post("/api/v1/retrieval/index", json=payload)
    r2 = retrieval_client.post("/api/v1/retrieval/index", json=payload)
    assert r1.json()["email_id"] == r2.json()["email_id"]
    assert r1.json()["was_created"] is True
    assert r2.json()["was_created"] is False


def test_index_requires_body(retrieval_client):
    response = retrieval_client.post("/api/v1/retrieval/index", json={"subject": "no body field"})
    assert response.status_code == 422


def test_search_finds_the_indexed_email(retrieval_client):
    retrieval_client.post(
        "/api/v1/retrieval/index",
        json={"subject": "Refund", "body": "I want a refund for my payment, please charge back my account.", "category": "Billing", "department": "Billing"},
    )
    retrieval_client.post(
        "/api/v1/retrieval/index",
        json={"subject": "Weather", "body": "The weather is nice today, lets walk in the park.", "category": "General", "department": "General"},
    )

    response = retrieval_client.post(
        "/api/v1/retrieval/search", json={"body": "I need help with a payment charge on my account", "top_k": 5}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result_count"] >= 1
    assert body["results"][0]["subject"] == "Refund"
    assert 0.0 <= body["results"][0]["score"] <= 1.0001  # cosine similarity, not a probability -- see schema docstring


def test_search_respects_top_k_default_of_5(retrieval_client):
    for i in range(8):
        retrieval_client.post(
            "/api/v1/retrieval/index",
            json={"subject": f"Refund {i}", "body": f"I want a refund {i}, payment charge account.", "category": "Billing", "department": "Billing"},
        )
    response = retrieval_client.post("/api/v1/retrieval/search", json={"body": "refund payment charge"})
    assert response.json()["result_count"] <= 5


def test_search_with_no_indexed_emails_returns_empty_not_an_error(retrieval_client):
    response = retrieval_client.post("/api/v1/retrieval/search", json={"body": "anything at all"})
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_resolution_status_update_and_filtering(retrieval_client):
    index_response = retrieval_client.post(
        "/api/v1/retrieval/index",
        json={"subject": "Refund", "body": "I want a refund payment charge account.", "category": "Billing", "department": "Billing"},
    )
    email_id = index_response.json()["email_id"]

    update_response = retrieval_client.patch(
        f"/api/v1/retrieval/emails/{email_id}/resolution", json={"resolution_status": "RESOLVED"}
    )
    assert update_response.status_code == 200
    assert update_response.json()["resolution_status"] == "RESOLVED"

    search_open = retrieval_client.post(
        "/api/v1/retrieval/search", json={"body": "refund payment charge", "resolution_status": "OPEN"}
    )
    assert search_open.json()["result_count"] == 0

    search_resolved = retrieval_client.post(
        "/api/v1/retrieval/search", json={"body": "refund payment charge", "resolution_status": "RESOLVED"}
    )
    assert search_resolved.json()["result_count"] == 1


def test_resolution_status_update_rejects_invalid_value(retrieval_client):
    index_response = retrieval_client.post(
        "/api/v1/retrieval/index", json={"subject": "X", "body": "refund payment"}
    )
    email_id = index_response.json()["email_id"]
    response = retrieval_client.patch(
        f"/api/v1/retrieval/emails/{email_id}/resolution", json={"resolution_status": "NOT_A_REAL_STATUS"}
    )
    assert response.status_code == 422


def test_resolution_status_update_rejects_malformed_email_id(retrieval_client):
    response = retrieval_client.patch(
        "/api/v1/retrieval/emails/not-a-valid-uuid/resolution", json={"resolution_status": "RESOLVED"}
    )
    assert response.status_code == 422


def test_delete_rejects_malformed_email_id(retrieval_client):
    response = retrieval_client.delete("/api/v1/retrieval/emails/not-a-valid-uuid")
    assert response.status_code == 422


def test_resolution_status_update_404s_for_unknown_email(retrieval_client):
    import uuid

    response = retrieval_client.patch(
        f"/api/v1/retrieval/emails/{uuid.uuid4()}/resolution", json={"resolution_status": "RESOLVED"}
    )
    assert response.status_code == 404


def test_delete_removes_email_from_search_results(retrieval_client):
    index_response = retrieval_client.post(
        "/api/v1/retrieval/index",
        json={"subject": "Refund", "body": "I want a refund payment charge account.", "category": "Billing", "department": "Billing"},
    )
    email_id = index_response.json()["email_id"]

    delete_response = retrieval_client.delete(f"/api/v1/retrieval/emails/{email_id}")
    assert delete_response.status_code == 204

    search_response = retrieval_client.post(
        "/api/v1/retrieval/search", json={"body": "refund payment charge account"}
    )
    assert search_response.json()["result_count"] == 0


def test_retrieval_feedback_is_logged(retrieval_client, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_retrieval_feedback_logger

    retrieval_client.app.dependency_overrides[get_retrieval_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="retrieval"
    )
    try:
        response = retrieval_client.post(
            "/api/v1/retrieval/feedback",
            json={"query_body": "refund", "result_email_id": None, "useful": True, "comment": "good match"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "logged"
        logged = (tmp_path / "retrieval_feedback.jsonl").read_text(encoding="utf-8")
        assert body["feedback_id"] in logged
    finally:
        del retrieval_client.app.dependency_overrides[get_retrieval_feedback_logger]
