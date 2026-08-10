"""
Versioned API router.

Why version at the router level (/api/v1/...) from day one:
    Retrofitting versioning after you have live consumers is painful — every
    client breaks the moment you change a response shape. Starting at /v1
    costs nothing now and means a future breaking change ships as /v2
    alongside the old one, not as a flag day for every integration.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    category,
    health,
    intent,
    priority,
    reply,
    retrieval,
    routing,
    sentiment,
    spam,
    summarization,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(spam.router)
api_router.include_router(priority.router)
api_router.include_router(category.router)
api_router.include_router(summarization.router)
api_router.include_router(sentiment.router)
api_router.include_router(intent.router)
api_router.include_router(routing.router)
api_router.include_router(retrieval.router)
api_router.include_router(reply.router)
