"""FastAPI application factory.

Routers stay thin per CLAUDE.md — orchestration belongs in ``services/`` and
rules belong in ``domain/``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from alam.api.middleware import TraceIDMiddleware
from alam.api.routers import health
from alam.config.logging import configure_logging, get_logger
from alam.config.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    get_logger(__name__).info("api.startup", env=settings.env)
    yield
    get_logger(__name__).info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ALAM",
        description="Adaptive Learning Associative Memory — a personal AI media companion.",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.add_middleware(TraceIDMiddleware)
    app.include_router(health.router)

    return app


app = create_app()
