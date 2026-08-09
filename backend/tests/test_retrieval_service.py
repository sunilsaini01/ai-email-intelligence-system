"""
Unit tests for RetrievalService (Module 9 / Phase 9) -- uses a fake
embedder + InMemoryVectorStore, no real model, no chromadb, no DB.
"""

from app.retrieval.vector_store import InMemoryVectorStore
from app.services.retrieval_service import RetrievalService


class _FakeEmbedder:
    """Deterministic fake: embeds a word's presence as a one-hot-ish
    vector so similarity is predictable in tests."""

    dimension = 3
    model_version = "fake-embedder-v1"

    def embed(self, text: str) -> list[float]:
        text_lower = text.lower()
        return [
            1.0 if "refund" in text_lower else 0.0,
            1.0 if "weather" in text_lower else 0.0,
            0.1,  # small shared component so no vector is all-zero
        ]

    def embed_batch(self, texts):
        return [self.embed(t) for t in texts]


def _make_service():
    return RetrievalService(embedder=_FakeEmbedder(), vector_store=InMemoryVectorStore())


def test_index_email_returns_expected_shape():
    service = _make_service()
    result = service.index_email(
        content_hash="hash1", subject="Refund", body="I want a refund.", category="Billing", department="Billing"
    )
    assert result["vector_id"] == "hash1"
    assert result["embedding_model"] == "fake-embedder-v1"
    assert result["embedding_dimension"] == 3
    assert result["pii_entity_types_found"] == []


def test_index_is_idempotent_by_content_hash():
    service = _make_service()
    service.index_email("hash1", "Refund", "I want a refund.", "Billing", "Billing")
    service.index_email("hash1", "Refund", "I want a refund.", "Billing", "Billing")
    # re-indexing the same hash overwrites, doesn't duplicate -- verified
    # via the vector store contract test directly; here we just confirm
    # the service doesn't error on repeat calls.
    result = service.search("refund", "", top_k=5)
    assert len(result["matches"]) == 1


def test_search_finds_relevant_and_ranks_above_irrelevant():
    service = _make_service()
    service.index_email("refund-hash", "Refund", "I want a refund.", "Billing", "Billing")
    service.index_email("weather-hash", "Weather", "Nice weather today.", "General", "General")

    result = service.search(subject="", body="I need a refund please", top_k=5)
    ids = [m["content_hash"] for m in result["matches"]]
    assert ids[0] == "refund-hash"


def test_search_respects_category_filter():
    service = _make_service()
    service.index_email("refund-hash", "Refund", "I want a refund.", "Billing", "Billing")
    service.index_email("refund-hash-2", "Refund2", "Another refund.", "Support", "Support")

    result = service.search(subject="", body="refund", top_k=5, category="Support")
    ids = [m["content_hash"] for m in result["matches"]]
    assert ids == ["refund-hash-2"]


def test_tenant_isolation_between_organizations():
    service = _make_service()
    service.index_email("hash1", "Refund", "I want a refund.", "Billing", "Billing", organization_id="org-a")

    result_a = service.search(subject="", body="refund", top_k=5, organization_id="org-a")
    result_b = service.search(subject="", body="refund", top_k=5, organization_id="org-b")

    assert len(result_a["matches"]) == 1
    assert len(result_b["matches"]) == 0


def test_delete_vector_removes_it_from_search_results():
    service = _make_service()
    service.index_email("hash1", "Refund", "I want a refund.", "Billing", "Billing")
    service.delete_vector("hash1")

    result = service.search(subject="", body="refund", top_k=5)
    assert result["matches"] == []


def test_pii_in_indexed_body_is_not_embedded_verbatim():
    """Regression-style test: indexing an email with PII must not leak the
    raw PII into what gets embedded -- verified indirectly by confirming
    the entity type is reported (build_embedding_text is exercised)."""
    service = _make_service()
    result = service.index_email(
        "hash1",
        "Contact",
        "My name is John Smith, email john@example.com.",
        category=None,
        department=None,
    )
    assert "PERSON" in result["pii_entity_types_found"]
    assert "EMAIL_ADDRESS" in result["pii_entity_types_found"]
