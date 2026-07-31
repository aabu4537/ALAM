"""Health endpoint.

Deliberately does not touch the database. ADR-0005 puts this endpoint on the
real URL at M0 as the platform's liveness signal, and a health check that fails
when Postgres blips causes the platform to recycle a web service that is fine.
Database readiness gets its own endpoint when there is a database to check.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from alam.config.settings import Environment, get_settings

router = APIRouter(tags=["ops"])


class HealthResponse(BaseModel):
    status: str
    env: Environment
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", env=settings.env, version="0.1.0")
