"""
Application factory.

Why a factory function (create_app) instead of a module-level `app = FastAPI()`:
    Tests need to spin up the app multiple times with different settings
    (e.g. overriding the DB dependency). A factory function makes that
    trivial. A module-level global app object makes that awkward and
    encourages tests that accidentally share state.
"""

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.middleware.exception_handlers import register_exception_handlers
from app.middleware.request_logging import RequestLoggingMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=f"/api/{settings.API_VERSION}")

    return app


app = create_app()
