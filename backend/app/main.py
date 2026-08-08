"""
Application factory.

Why a factory function (create_app) instead of a module-level `app = FastAPI()`:
    Tests need to spin up the app multiple times with different settings
    (e.g. overriding the DB dependency). A factory function makes that
    trivial. A module-level global app object makes that awkward and
    encourages tests that accidentally share state.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.middleware.exception_handlers import register_exception_handlers
from app.middleware.request_logging import RequestLoggingMiddleware
from app.services.category_service import get_category_service
from app.services.intent_service import get_intent_service
from app.services.priority_service import get_priority_service
from app.services.sentiment_service import get_sentiment_service
from app.services.spam_service import get_spam_service
from app.services.summarization_service import get_summarization_service

logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Eagerly constructs the ML services at process startup instead of
    lazily on whichever request happens to arrive first.

    Why this matters: get_spam_service()/get_priority_service() are
    @lru_cache'd, so the first call in a process pays a real, measured cost
    (see docs/architecture_priority_classification.md "Performance" —
    priority's first construction took ~29s in this environment, almost
    entirely an implicit module import triggered by unpickling, not slow
    deserialization). Without this, that cost silently lands on a live
    user's first request. With it, it's paid once during deployment/startup,
    where a slow response doesn't mean anything to anyone.

    Why failures here are logged, not raised: a missing model artifact
    (fresh clone, training hasn't run yet) shouldn't prevent the app from
    starting — the existing per-request 503 (SpamServiceUnavailable /
    PriorityServiceUnavailable) already handles that case correctly. This
    mirrors the same graceful-degradation stance as the liveness/readiness
    split in docs/architecture.md: a missing dependency degrades one
    capability, it doesn't take down the process.

    Why this is invisible to the existing test suite: plain
    `TestClient(app)` (tests/conftest.py's `client` fixture) does not run
    ASGI lifespan events at all — only `with TestClient(app) as client:`
    does. Verified empirically before relying on it; see
    tests/test_startup_warmup.py for the test that actually exercises this.
    """
    # summarization deliberately included here: constructing
    # SummarizationService only builds the extractive (TextRank) path,
    # which is cheap. The abstractive path lazy-loads on first actual use
    # instead — see app/services/summarization_service.py's module
    # docstring for why (its ~115s first-load cost would otherwise nearly
    # double this process's startup time for a path most requests won't use).
    #
    # sentiment is the cheapest of all five: SentimentIntensityAnalyzer()
    # just loads a small, fixed lexicon shipped inside the vaderSentiment
    # package — no model download, no unpickling, nothing analogous to
    # priority's ~29s first-construction cost.
    for name, get_service in (
        ("spam", get_spam_service),
        ("priority", get_priority_service),
        ("category", get_category_service),
        ("summarization", get_summarization_service),
        ("sentiment", get_sentiment_service),
        ("intent", get_intent_service),
    ):
        try:
            get_service()
            logger.info(f"{name}_service_warmed_up")
        except Exception:
            logger.warning(f"{name}_service_warmup_failed", exc_info=True)

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=f"/api/{settings.API_VERSION}")

    return app


app = create_app()
