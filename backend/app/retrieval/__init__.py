"""
Retrieval-specific building blocks (Module 9 / Phase 9).

Same "pure logic vs. service wiring" split app/routing/ established for
Module 8: this package holds dependency-free logic (content-hash identity,
embedding-input construction, the VectorStore abstraction + an in-memory
fake, tenant/resolution-status constants) that is independently testable
without a real vector store, a real embedding model, or a database.
`RetrievalService` (app/services/retrieval_service.py) composes these with
the real embedders, the real vector store, and the `emails` table.
"""
