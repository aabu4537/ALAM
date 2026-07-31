"""Request middleware.

The trace id is accepted from an inbound ``X-Request-ID`` when present so a
proxy or the PWA can correlate across the split deployment (ADR-0005), and
generated otherwise. It is bound into structlog's contextvars, which means
every log line produced anywhere downstream of this middleware carries it
without being passed explicitly.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from alam.config.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

TRACE_HEADER = "X-Request-ID"

log = get_logger(__name__)


class TraceIDMiddleware(BaseHTTPMiddleware):
    """Bind a trace id to the log context and echo it on the response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_id = request.headers.get(TRACE_HEADER) or uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request.failed",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()
            raise

        log.info(
            "request.completed",
            status_code=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )

        response.headers[TRACE_HEADER] = trace_id
        structlog.contextvars.clear_contextvars()
        return response
