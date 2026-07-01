"""
Request logging middleware.

Why middleware, not logging inside each route:
    Every route would need to remember to log timing/status — they will
    forget. Middleware guarantees every request gets logged exactly once,
    with the same fields, regardless of which route handled it.

What this deliberately does NOT log:
    Request bodies. Email content (PII) flows through this app. Logging
    raw bodies at the middleware level is a generic, easy-to-introduce PII
    leak that would apply to every endpoint, present and future. Log
    metadata (path, status, latency) here; log domain-specific, scrubbed
    fields inside the service layer if needed.
"""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        logger.info(
            "request_handled",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response
