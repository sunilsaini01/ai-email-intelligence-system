"""
Integration tests for the Auto-Reply endpoints (Module 10 / Phase 10,
FR-48 to FR-52). Uses FakeLLMProvider (never a real API call) and a fake
RetrievalService (InMemoryVectorStore + deterministic fake embedder, same
pattern tests/test_retrieval_service.py established) -- no network, no
Chroma, no real DB, fully deterministic.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.repositories.email_repository import EmailRepository
from app.database.session import Base, get_db
from app.inference.fake_llm_provider import FakeLLMProvider
from app.main import create_app
from app.models.reply_draft import (
    POLICY_LLM_FAILURE,
    POLICY_NO_SIMILAR_EMAILS,
    POLICY_NORMAL_REPLY,
    POLICY_TIMEOUT,
    STATUS_FAILED,
    STATUS_GENERATED,
)
from app.retrieval.resolution_status import OPEN, RESOLVED
from app.retrieval.vector_store import InMemoryVectorStore
from app.services.auto_reply_service import AutoReplyService, get_auto_reply_service
from app.services.retrieval_service import RetrievalService, get_retrieval_service
from tests.test_retrieval_service import _FakeEmbedder


@pytest_asyncio.fixture
async def sqlite_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


async def _seed_resolved_email(session_factory, content_hash: str, resolution_status: str = RESOLVED):
    async with session_factory() as session:
        from datetime import UTC, datetime

        repo = EmailRepository(session)
        record, _ = await repo.upsert_by_content_hash(
            organization_id="default",
            content_hash=content_hash,
            subject="Past refund case",
            body="We processed your refund for the order.",
            sender_email="support@example.com",
            received_at=datetime.now(UTC),
            category="Billing",
            department="Billing",
        )
        if resolution_status != OPEN:  # OPEN is the default already
            await repo.update_resolution_status("default", record.id, resolution_status)
        return record.id


def _make_client(session_factory, fake_retrieval_service, fake_llm_response="Here is your draft reply."):
    get_retrieval_service.cache_clear()
    get_auto_reply_service.cache_clear()

    fake_auto_reply_service = AutoReplyService(llm_provider=FakeLLMProvider(response_text=fake_llm_response))

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_retrieval_service] = lambda: fake_retrieval_service
    app.dependency_overrides[get_auto_reply_service] = lambda: fake_auto_reply_service

    return TestClient(app), fake_auto_reply_service


@pytest.fixture
def empty_retrieval_service():
    return RetrievalService(embedder=_FakeEmbedder(), vector_store=InMemoryVectorStore())


def test_generate_with_no_indexed_emails_still_returns_a_draft(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    response = client.post("/api/v1/reply/generate", json={"subject": "Question", "body": "What are your hours?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == STATUS_GENERATED
    assert body["generation_policy"] == POLICY_NO_SIMILAR_EMAILS
    assert body["retrieved_context_count"] == 0
    assert body["generated_text"].startswith("Here is your draft reply.")
    assert "limited historical context" in body["generated_text"]  # confidence-gate warning, 0 context items


@pytest.mark.asyncio
async def test_generate_finds_resolved_similar_email_as_context(sqlite_session_factory):
    email_id = await _seed_resolved_email(sqlite_session_factory, content_hash="hash-resolved-1", resolution_status=RESOLVED)

    retrieval_service = RetrievalService(embedder=_FakeEmbedder(), vector_store=InMemoryVectorStore())
    retrieval_service.index_email(
        content_hash="hash-resolved-1", subject="Past refund case", body="refund processed", category="Billing", department="Billing"
    )

    client, _ = _make_client(sqlite_session_factory, retrieval_service)
    response = client.post("/api/v1/reply/generate", json={"subject": "Refund", "body": "I want a refund please."})

    assert response.status_code == 200
    body = response.json()
    assert body["generation_policy"] == POLICY_NORMAL_REPLY
    assert body["retrieved_context_count"] == 1
    assert str(email_id) in body["retrieved_email_ids"]


@pytest.mark.asyncio
async def test_generate_ignores_unresolved_similar_email(sqlite_session_factory):
    """A vector-similar email that is NOT resolution_status=RESOLVED must
    never be used as context -- FR-48's literal requirement."""
    await _seed_resolved_email(sqlite_session_factory, content_hash="hash-open-1", resolution_status=OPEN)

    retrieval_service = RetrievalService(embedder=_FakeEmbedder(), vector_store=InMemoryVectorStore())
    retrieval_service.index_email(
        content_hash="hash-open-1", subject="Past refund case", body="refund processed", category="Billing", department="Billing"
    )

    client, _ = _make_client(sqlite_session_factory, retrieval_service)
    response = client.post("/api/v1/reply/generate", json={"subject": "Refund", "body": "I want a refund please."})

    assert response.status_code == 200
    body = response.json()
    assert body["retrieved_context_count"] == 0
    assert body["generation_policy"] == POLICY_NO_SIMILAR_EMAILS


def test_generate_records_llm_timeout_as_failed_draft(sqlite_session_factory, empty_retrieval_service):
    get_retrieval_service.cache_clear()
    get_auto_reply_service.cache_clear()

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_retrieval_service] = lambda: empty_retrieval_service
    app.dependency_overrides[get_auto_reply_service] = lambda: AutoReplyService(llm_provider=FakeLLMProvider(raise_timeout=True))
    client = TestClient(app)

    response = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == STATUS_FAILED
    assert body["generation_policy"] == POLICY_TIMEOUT
    assert body["generated_text"] is None


def test_generate_records_llm_provider_error_as_failed_draft(sqlite_session_factory, empty_retrieval_service):
    get_retrieval_service.cache_clear()
    get_auto_reply_service.cache_clear()

    async def override_get_db():
        async with sqlite_session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_retrieval_service] = lambda: empty_retrieval_service
    app.dependency_overrides[get_auto_reply_service] = lambda: AutoReplyService(llm_provider=FakeLLMProvider(raise_error=True))
    client = TestClient(app)

    response = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == STATUS_FAILED
    assert body["generation_policy"] == POLICY_LLM_FAILURE


def test_generate_requires_body(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    response = client.post("/api/v1/reply/generate", json={"subject": "no body field"})
    assert response.status_code == 422


def test_get_unknown_draft_returns_404(sqlite_session_factory, empty_retrieval_service):
    import uuid

    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    response = client.get(f"/api/v1/reply/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_malformed_draft_id_returns_422(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    response = client.get("/api/v1/reply/not-a-uuid")
    assert response.status_code == 422


def test_full_lifecycle_generate_then_approve(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/approve", json={"reviewer_id": "agent-1"})
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"


def test_full_lifecycle_generate_then_edit(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/edit", json={"edited_text": "A better reply.", "reviewer_id": "agent-1"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "EDITED"
    assert body["edited_text"] == "A better reply."
    assert body["edit_distance"] is not None and body["edit_distance"] > 0  # Post-Phase-10 fix #2


def test_approve_and_reject_leave_edit_distance_null_in_response(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/approve", json={})
    assert response.json()["edit_distance"] is None


def test_edit_rejects_empty_text(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/edit", json={"edited_text": ""})
    assert response.status_code == 422


def test_full_lifecycle_generate_then_reject(sqlite_session_factory, empty_retrieval_service):
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/reject", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_approve_unknown_draft_returns_404(sqlite_session_factory, empty_retrieval_service):
    import uuid

    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    response = client.post(f"/api/v1/reply/{uuid.uuid4()}/approve", json={})
    assert response.status_code == 404


# --- Post-Phase-10 fix #3: auto-mark-resolved on approve ---


@pytest.mark.asyncio
async def test_approve_auto_marks_source_email_resolved(sqlite_session_factory):
    """When source_email_id is supplied and the draft is approved, the
    referenced email's resolution_status must flip to RESOLVED -- the
    mechanism that starts closing docs/architecture_auto_reply.md's own
    'Resolved-Email Data Reality' gap."""
    email_id = await _seed_resolved_email(sqlite_session_factory, content_hash="hash-to-resolve", resolution_status=OPEN)
    empty_service = RetrievalService(embedder=_FakeEmbedder(), vector_store=InMemoryVectorStore())
    client, _ = _make_client(sqlite_session_factory, empty_service)

    draft_id = client.post(
        "/api/v1/reply/generate", json={"subject": "Q", "body": "body", "source_email_id": str(email_id)}
    ).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/approve", json={"reviewer_id": "agent-1"})
    assert response.status_code == 200

    async with sqlite_session_factory() as session:
        record = await EmailRepository(session).get_by_id("default", email_id)
        assert record.resolution_status == RESOLVED


def test_approve_without_source_email_id_does_not_crash(sqlite_session_factory, empty_retrieval_service):
    """No source_email_id (the common case -- see FR-48's own audit finding
    that indexing isn't required for /reply/generate) -- approve must still
    succeed, the auto-resolve side effect is simply skipped."""
    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/approve", json={"reviewer_id": "agent-1"})
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"


def test_approve_with_nonexistent_source_email_id_does_not_crash(sqlite_session_factory, empty_retrieval_service):
    """source_email_id pointing at nothing real (never indexed, or deleted
    since) -- the auto-resolve attempt fails silently (best-effort), the
    approve action itself must still succeed."""
    import uuid

    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post(
        "/api/v1/reply/generate", json={"subject": "Q", "body": "body", "source_email_id": str(uuid.uuid4())}
    ).json()["draft_id"]

    response = client.post(f"/api/v1/reply/{draft_id}/approve", json={"reviewer_id": "agent-1"})
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"


@pytest.mark.asyncio
async def test_reject_does_not_auto_resolve(sqlite_session_factory):
    """Only APPROVE triggers auto-resolve -- a rejected draft says nothing
    about whether the underlying situation was actually handled."""
    email_id = await _seed_resolved_email(sqlite_session_factory, content_hash="hash-not-resolved", resolution_status=OPEN)
    empty_service = RetrievalService(embedder=_FakeEmbedder(), vector_store=InMemoryVectorStore())
    client, _ = _make_client(sqlite_session_factory, empty_service)

    draft_id = client.post(
        "/api/v1/reply/generate", json={"subject": "Q", "body": "body", "source_email_id": str(email_id)}
    ).json()["draft_id"]
    client.post(f"/api/v1/reply/{draft_id}/reject", json={})

    async with sqlite_session_factory() as session:
        record = await EmailRepository(session).get_by_id("default", email_id)
        assert record.resolution_status == OPEN


def test_feedback_endpoint_logs_and_returns_id(sqlite_session_factory, empty_retrieval_service, tmp_path):
    from app.services.feedback_service import FeedbackLogger, get_auto_reply_feedback_logger

    client, _ = _make_client(sqlite_session_factory, empty_retrieval_service)
    draft_id = client.post("/api/v1/reply/generate", json={"subject": "Q", "body": "body"}).json()["draft_id"]

    client.app.dependency_overrides[get_auto_reply_feedback_logger] = lambda: FeedbackLogger(
        artifact_dir=str(tmp_path), module="auto_reply"
    )
    response = client.post("/api/v1/reply/feedback", json={"draft_id": draft_id, "useful": True, "comment": "good draft"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "logged"
    logged = (tmp_path / "auto_reply_feedback.jsonl").read_text(encoding="utf-8")
    assert body["feedback_id"] in logged
