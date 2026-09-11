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

from app.core.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL

logger = logging.getLogger("app.request")

# Phase 16B / FR-72: the metrics scrape endpoint itself is excluded from
# HTTP_REQUESTS_TOTAL/HTTP_REQUEST_DURATION_SECONDS -- a Prometheus metric
# counting its own scrapes is pure self-referential noise with no signal
# value, unlike /health traffic below, which IS recorded (under its own
# path_template label, so it never pollutes any other endpoint's latency
# histogram -- Prometheus buckets are per label combination).
_EXCLUDED_FROM_METRICS = frozenset({"/metrics"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        response = await call_next(request)

        duration_seconds = time.perf_counter() - start_time
        duration_ms = round(duration_seconds * 1000, 2)

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

        if request.url.path not in _EXCLUDED_FROM_METRICS:
            # request.scope["route"].path is the FastAPI route TEMPLATE
            # (e.g. "/api/v1/workflows/{job_id}"), not the resolved path
            # with a real UUID in it -- using the raw path here would give
            # every distinct job_id its own label series, an unbounded-
            # cardinality metric that would eventually crash Prometheus.
            # Falls back to a fixed sentinel (never the raw path) for
            # genuinely unmatched routes (404s) -- this project has no
            # auth yet (docs/architecture.md), so an unauthenticated
            # caller probing random paths must not be able to grow this
            # metric's cardinality without bound.
            route = request.scope.get("route")
            path_template = route.path if route is not None else "unmatched"

            HTTP_REQUESTS_TOTAL.labels(
                method=request.method, path_template=path_template, status_code=str(response.status_code)
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, path_template=path_template).observe(
                duration_seconds
            )

        response.headers["X-Request-ID"] = request_id
        return response
