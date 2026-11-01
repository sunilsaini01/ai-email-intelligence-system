"""
Per-organization API rate limiting (PRD SS13.1: "Rate Limits: 1,000
req/min per organization (configurable)").

A plain ASGI middleware, not a BaseHTTPMiddleware subclass -- the latter
is one of the layers implicated in this project's DB-write hang
investigation (docs/technical_debt/database_write_hang.md), and a rate
limiter has no reason to wrap the response stream at all.

Fixed one-minute windows keyed by the caller's organization (from a
verified JWT -- see app/core/request_principal.py), falling back to the
client IP for unauthenticated traffic (login/register brute force is the
case that matters there). Health probes and the Prometheus scrape are
never limited.

Scope, stated plainly: counters live in this process's memory, so with N
API replicas the effective limit is N x RATE_LIMIT_PER_MINUTE. The PRD's
architecture puts rate limiting in the API gateway (SS10.1), which is
where a cluster-wide limit belongs once one is deployed; this is the
in-app backstop until then.
"""

import json
import time

from app.core.config import get_settings
from app.core.request_principal import principal_from_headers

_EXEMPT_PREFIXES = ("/api/v1/health", "/metrics")


class RateLimitMiddleware:
    def __init__(self, app, limit_per_minute: int | None = None):
        self.app = app
        self.limit = limit_per_minute or get_settings().RATE_LIMIT_PER_MINUTE
        self._window: int = 0
        self._counts: dict[str, int] = {}

    def _bucket_key(self, scope) -> str:
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        principal = principal_from_headers(headers)
        if principal.organization_id:
            return f"org:{principal.organization_id}"
        client = scope.get("client")
        return f"ip:{client[0] if client else 'unknown'}"

    def _hit(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, seconds until the window resets)."""
        now = time.time()
        window = int(now // 60)
        if window != self._window:
            self._window = window
            self._counts = {}
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key] <= self.limit, 60 - int(now % 60)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        allowed, retry_after = self._hit(self._bucket_key(scope))
        if allowed:
            await self.app(scope, receive, send)
            return

        body = json.dumps(
            {
                "type": "about:blank",
                "title": "Too Many Requests",
                "status": 429,
                "detail": f"Rate limit of {self.limit} requests per minute exceeded.",
                "instance": scope.get("path", ""),
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"retry-after", str(retry_after).encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
