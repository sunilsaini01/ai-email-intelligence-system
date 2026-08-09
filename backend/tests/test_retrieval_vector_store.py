"""
Unit tests for the VectorStore abstraction (Module 9 / Phase 9).

Both `InMemoryVectorStore` and `ChromaVectorStore` are tested against the
SAME contract via `_run_contract_tests` -- if a future third
implementation (e.g. a Pinecone one) doesn't satisfy this, that's a real
bug, not a test-specific quirk. `ChromaVectorStore` uses a fresh temp
directory per test (via `tmp_path`), never `artifacts/chroma/` -- no test
in this suite touches the real, persistent, application-used store.
"""

import pytest

from app.retrieval.chroma_vector_store import ChromaVectorStore
from app.retrieval.vector_store import InMemoryVectorStore

COLLECTION = "test_collection"
ORG_A = "org-a"
ORG_B = "org-b"


def _run_contract_tests(store):
    # --- basic upsert + query ---
    store.upsert(COLLECTION, ORG_A, "v1", [1.0, 0.0, 0.0], {"category": "Billing"})
    store.upsert(COLLECTION, ORG_A, "v2", [0.0, 1.0, 0.0], {"category": "Support"})
    results = store.query(COLLECTION, ORG_A, [1.0, 0.0, 0.0], top_k=5)
    assert results[0].id == "v1"
    assert results[0].score > results[1].score

    # --- idempotent upsert: same id overwrites, doesn't duplicate ---
    store.upsert(COLLECTION, ORG_A, "v1", [1.0, 0.0, 0.0], {"category": "Legal"})
    results = store.query(COLLECTION, ORG_A, [1.0, 0.0, 0.0], top_k=10)
    v1_matches = [r for r in results if r.id == "v1"]
    assert len(v1_matches) == 1
    assert v1_matches[0].metadata["category"] == "Legal"

    # --- tenant isolation: org B never sees org A's vectors ---
    results_b = store.query(COLLECTION, ORG_B, [1.0, 0.0, 0.0], top_k=10)
    assert results_b == []

    # --- metadata filtering ---
    filtered = store.query(COLLECTION, ORG_A, [1.0, 0.0, 0.0], top_k=10, where={"category": "Support"})
    assert [r.id for r in filtered] == ["v2"]

    # --- delete ---
    store.delete(COLLECTION, ORG_A, "v2")
    results = store.query(COLLECTION, ORG_A, [1.0, 0.0, 0.0], top_k=10)
    assert "v2" not in [r.id for r in results]

    # --- delete of a nonexistent id is a no-op, not an error ---
    store.delete(COLLECTION, ORG_A, "does-not-exist")


def test_in_memory_vector_store_satisfies_the_contract():
    _run_contract_tests(InMemoryVectorStore())


def test_chroma_vector_store_satisfies_the_contract(tmp_path):
    _run_contract_tests(ChromaVectorStore(persist_dir=str(tmp_path)))


def test_query_on_empty_collection_returns_empty_not_an_error():
    store = InMemoryVectorStore()
    assert store.query(COLLECTION, ORG_A, [1.0, 0.0], top_k=5) == []


def test_chroma_query_on_empty_collection_returns_empty_not_an_error(tmp_path):
    store = ChromaVectorStore(persist_dir=str(tmp_path))
    assert store.query(COLLECTION, ORG_A, [1.0, 0.0], top_k=5) == []


def test_score_is_higher_for_more_similar_vectors():
    store = InMemoryVectorStore()
    store.upsert(COLLECTION, ORG_A, "close", [1.0, 0.1, 0.0], {})
    store.upsert(COLLECTION, ORG_A, "far", [0.0, 0.0, 1.0], {})
    results = store.query(COLLECTION, ORG_A, [1.0, 0.0, 0.0], top_k=2)
    assert results[0].id == "close"
    assert results[0].score > results[1].score


@pytest.mark.parametrize("store_factory", [lambda: InMemoryVectorStore()])
def test_top_k_is_respected(store_factory):
    store = store_factory()
    for i in range(10):
        store.upsert(COLLECTION, ORG_A, f"v{i}", [1.0, float(i)], {})
    results = store.query(COLLECTION, ORG_A, [1.0, 0.0], top_k=3)
    assert len(results) == 3
