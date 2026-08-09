"""
RetrievalService (Module 9 / Phase 9).

Deliberately narrow: this class only knows how to (a) turn text into a
PII-scrubbed embedding and (b) talk to the vector store. It has NO
database session and NEVER touches `emails` directly -- DB orchestration
(idempotent upsert-by-content-hash, marking index_status, resolution-
status updates, soft delete) lives in the API endpoint
(app/api/v1/endpoints/retrieval.py), the same "service does the sync/CPU-
bound work, the endpoint does the async DB calls" split every other
module uses. What's specific to Phase 9: indexing and searching are each
a short multi-step DB+service sequence (DB upsert to get the row settled
-> embed+vector-upsert -> DB mark-indexed), not a single service call
followed by one log write -- documented here rather than silently
deviating from the established shape without explanation.

Vector identity == content_hash (app/retrieval/identity.py), not a
DB-generated UUID -- this is what makes indexing genuinely idempotent
end-to-end: re-indexing identical (subject, body) produces the exact same
vector_id, so the vector store's upsert naturally overwrites rather than
duplicates, with no coordination needed between Postgres and the vector
store to detect "is this the same email." It's also what makes a
category/department CHANGE (Step 19) work correctly with no special
lifecycle code: the caller re-calls index() with the same content and new
category/department, and the same vector_id gets its metadata overwritten.

`resolution_status` and `is_deleted` are deliberately NEVER written into
vector-store metadata (RULE 12 -- "do not allow stale metadata to produce
incorrect filtering"): resolution_status changes via a path
(PATCH /retrieval/emails/{id}/resolution) that does not re-embed, so
storing it in the vector store would drift out of sync the first time an
agent marks something resolved. Both are filtered against Postgres
(the single always-current source for mutable state) at query time in the
endpoint, not against the vector store. Soft-delete additionally calls
`delete_vector()` immediately (not lazily) so a deleted email's vector is
actually gone, not just filtered out after the fact.
"""

import logging
from functools import lru_cache

from app.retrieval.embedding_input import build_embedding_text
from app.retrieval.tenant import DEFAULT_ORGANIZATION_ID
from app.retrieval.vector_store import VectorMatch, VectorStore

logger = logging.getLogger("app.retrieval")

VECTOR_COLLECTION = "email_embeddings_v1"  # Step 18 -- index versioning lives in the name itself


class RetrievalService:
    def __init__(self, embedder=None, vector_store: VectorStore | None = None):
        self._embedder = embedder
        self._vector_store = vector_store

    def _resolve_embedder(self):
        if self._embedder is not None:
            return self._embedder
        from app.inference.tfidf_embedder import TfidfEmbedder

        return TfidfEmbedder()

    def _resolve_vector_store(self) -> VectorStore:
        if self._vector_store is not None:
            return self._vector_store
        from app.retrieval.chroma_vector_store import ChromaVectorStore

        return ChromaVectorStore()

    def index_email(
        self,
        content_hash: str,
        subject: str,
        body: str,
        category: str | None,
        department: str | None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> dict:
        anonymized_text, pii_entity_types = build_embedding_text(subject, body)
        embedder = self._resolve_embedder()
        embedding = embedder.embed(anonymized_text)

        metadata = {"category": category, "department": department, "content_hash": content_hash}
        self._resolve_vector_store().upsert(
            collection=VECTOR_COLLECTION,
            organization_id=organization_id,
            vector_id=content_hash,
            embedding=embedding,
            metadata=metadata,
        )

        return {
            "vector_id": content_hash,
            "collection": VECTOR_COLLECTION,
            "embedding_model": embedder.model_version,
            "embedding_dimension": embedder.dimension,
            "pii_entity_types_found": pii_entity_types,
        }

    def search(
        self,
        subject: str,
        body: str,
        top_k: int,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        category: str | None = None,
        department: str | None = None,
    ) -> dict:
        anonymized_text, _ = build_embedding_text(subject, body)
        embedder = self._resolve_embedder()
        embedding = embedder.embed(anonymized_text)

        where = {k: v for k, v in {"category": category, "department": department}.items() if v is not None}
        matches: list[VectorMatch] = self._resolve_vector_store().query(
            collection=VECTOR_COLLECTION,
            organization_id=organization_id,
            embedding=embedding,
            top_k=top_k,
            where=where or None,
        )

        return {
            "matches": [{"content_hash": m.id, "score": m.score, "metadata": m.metadata} for m in matches],
            "collection": VECTOR_COLLECTION,
            "embedding_model": embedder.model_version,
        }

    def delete_vector(self, content_hash: str, organization_id: str = DEFAULT_ORGANIZATION_ID) -> None:
        self._resolve_vector_store().delete(
            collection=VECTOR_COLLECTION, organization_id=organization_id, vector_id=content_hash
        )


@lru_cache
def get_retrieval_service() -> RetrievalService:
    return RetrievalService()
