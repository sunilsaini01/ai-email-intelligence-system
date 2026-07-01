"""
Centralized exception handling.

Why this exists:
    Without it, an unhandled exception anywhere in the app produces FastAPI's
    default 500 response — which, depending on config, can leak stack traces
    to clients (an information disclosure risk) and gives every client a
    different error shape depending on where the failure happened.

    This file guarantees: every error response has the same shape (RFC 7807
    Problem Details, matching the API design decision in the PRD), internal
    details are logged server-side but never sent to the client, and the
    error is logged with enough context to debug without reproducing it.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.errors")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            extra={"path": request.url.path, "error": str(exc)},
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "type": "about:blank",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred. This has been logged.",
                "instance": str(request.url.path),
            },
        )
