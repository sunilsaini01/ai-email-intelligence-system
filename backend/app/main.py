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

# Import-order workaround (Phase 9): `sklearn` and `pandas` are imported
# directly and FIRST among this file's real dependencies -- before
# `app.api.v1.router` below, which is what transitively imports both
# `transformers` (Module 6, summarization) and this project's retrieval
# code (Module 9). Reason, verified by direct reproduction (see
# docs/error_analysis_retrieval.md for the exact repro commands): once
# Module 9's `retrieval` endpoint entered the router's import sweep
# alongside `summarization`, the combination of `transformers`' lazy-module
# `__getattr__` resolving a `sklearn`/`pandas`/`pyarrow` import for the
# FIRST time triggers a Windows-specific fault in this exact dependency-
# version combination -- an access violation in `pyarrow` before this fix,
# a stack overflow in a circular lazy-import chain after a first, partial
# fix (making app/security/pii_anonymizer.py's Presidio engines lazy,
# still correct and kept, but insufficient alone). Forcing `sklearn`/
# `pandas` into `sys.modules` before `transformers` ever gets a chance to
# trigger that resolution path itself sidesteps the fault entirely --
# confirmed empirically, not merely theorized. This is an environment/
# dependency-version workaround, not an application concern; revisit if
# `transformers`/`scikit-learn`/`pandas`/`pyarrow` are ever upgraded
# together and this comment's reproduction no longer applies.
import pandas  # noqa: F401,E402
import sklearn  # noqa: F401,E402

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.middleware.exception_handlers import register_exception_handlers
from app.middleware.request_logging import RequestLoggingMiddleware
from app.services.auto_reply_service import get_auto_reply_service
from app.services.category_service import get_category_service
from app.services.intent_service import get_intent_service
from app.services.priority_service import get_priority_service
from app.services.retrieval_service import get_retrieval_service
from app.services.routing_service import get_routing_service
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
    # sentiment is the cheapest of the first five: SentimentIntensityAnalyzer()
    # just loads a small, fixed lexicon shipped inside the vaderSentiment
    # package — no model download, no unpickling, nothing analogous to
    # priority's ~29s first-construction cost.
    #
    # routing is cheaper still: RoutingService's constructor does nothing
    # but store None defaults — it resolves spam/priority/category/
    # sentiment/intent lazily, per-request, inside route() (see
    # app/services/routing_service.py's module docstring on why: a
    # RoutingService that ate one upstream service's construction failure
    # would defeat its own per-signal failure isolation). Warmed up here
    # only for symmetry with every other module's startup log line.
    for name, get_service in (
        ("spam", get_spam_service),
        ("priority", get_priority_service),
        ("category", get_category_service),
        ("summarization", get_summarization_service),
        ("sentiment", get_sentiment_service),
        ("intent", get_intent_service),
        ("routing", get_routing_service),
    ):
        try:
            get_service()
            logger.info(f"{name}_service_warmed_up")
        except Exception:
            logger.warning(f"{name}_service_warmup_failed", exc_info=True)

    # retrieval: RetrievalService itself is lazy like RoutingService (same
    # per-signal-failure-isolation reasoning), so get_retrieval_service()
    # alone warms up nothing. Unlike routing, this one's worth forcing
    # further: the default embedder (MiniLmEmbedder as of Phase 10 — see
    # docs/architecture_auto_reply.md "Embedder Decision") downloads/loads
    # real transformer weights whose cost belongs at startup, not a live
    # caller's first /retrieval/index, /retrieval/search, or /reply/generate
    # request — same reasoning as every classifier service above. Failure
    # here (e.g. no network on first-ever run to fetch the weights) degrades
    # gracefully, same as every other warmup in this loop.
    # Both _resolve_embedder() and _resolve_vector_store() are memoized on
    # the RetrievalService singleton (fixed during Phase 10 end-to-end
    # testing -- they used to reconstruct on every call, invisible with
    # TF-IDF's cheap construction, but a real measured ~1.4s/request cost
    # once MiniLM became the default). Warming BOTH here, not just the
    # embedder: Chroma's PersistentClient has its own real, measured
    # multi-second cold start independent of the embedding model (ONNX
    # runtime / hnswlib index setup), so warming only the embedder still
    # left a live caller's first request to pay Chroma's cold start alone.
    try:
        service = get_retrieval_service()
        service._resolve_embedder()  # noqa: SLF001 -- warmup-only internal reach
        service._resolve_vector_store()  # noqa: SLF001 -- warmup-only internal reach
        logger.info("retrieval_service_warmed_up")
    except Exception:
        logger.warning("retrieval_service_warmup_failed", exc_info=True)

    # auto_reply: AutoReplyService() itself is cheap (no network call);
    # forcing _resolve_llm_provider() here only constructs the Groq SDK
    # client object (also no network call) but DOES surface a missing
    # GROQ_API_KEY loudly at startup instead of on a live caller's first
    # /reply/generate request -- same reasoning as every warmup above.
    try:
        get_auto_reply_service()._resolve_llm_provider()  # noqa: SLF001 -- warmup-only internal reach
        logger.info("auto_reply_service_warmed_up")
    except Exception:
        logger.warning("auto_reply_service_warmup_failed", exc_info=True)

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

    # Phase 11: allows the frontend/ dashboard (a different origin in dev,
    # e.g. localhost:5173) to call this API and open its WebSocket at all.
    # Explicit origin list, not "*" -- see Settings.CORS_ORIGINS docstring.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGIN_LIST,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=f"/api/{settings.API_VERSION}")

    return app


app = create_app()
