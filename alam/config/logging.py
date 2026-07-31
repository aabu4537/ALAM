"""Structured logging setup.

Both the web service and the worker log to stdout as JSON in deployed
environments, so Render's log drain and any later aggregator get parseable
events rather than formatted strings. ``console`` format stays available for
local work.

Every log line emitted during a request carries the request's ``trace_id``,
bound once by the middleware in ``alam.api.middleware`` and picked up from
contextvars — handlers never thread it through by hand.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from alam.config.settings import LogFormat


def configure_logging(level: str = "INFO", fmt: LogFormat = "json") -> None:
    """Configure structlog and route stdlib logging through it.

    Idempotent — safe to call from both the API lifespan and the worker
    entrypoint.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
        force=True,
    )

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Prefer module-level ``__name__``."""
    return structlog.stdlib.get_logger(name)
