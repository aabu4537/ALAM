"""Internal operations endpoints.

Not part of the public API. The drain endpoint is the production trigger under
ADR-0007 — Supabase Cron calls it on a schedule — and it is a public URL, so it
requires a shared secret. On a metered free tier an open drain is a billing
problem as much as a correctness one.

The demo seed endpoint is the same shape (public URL, shared secret, fails
closed when unconfigured) for a different reason: it writes data, and an open
write endpoint is a spam vector even though the data it writes is fixed and
harmless.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from alam.config.settings import Settings, get_settings
from alam.jobs.runner import drain
from alam.persistence.session import get_session_factory, session_scope
from alam.services.demo_persona import seed_demo_persona

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(prefix="/internal", tags=["internal"])


def require_drain_secret(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Bearer check using a constant-time comparison.

    Refuses outright when no secret is configured rather than defaulting to
    open — an unset environment variable should fail closed.
    """
    expected = settings.drain_secret
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="drain endpoint is not configured",
        )

    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:]

    if not secrets.compare_digest(presented, expected.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing drain credentials",
        )


class DrainResponse(BaseModel):
    claimed: int
    succeeded: int
    failed: int
    budget_exhausted: bool


@router.post(
    "/jobs/drain",
    response_model=DrainResponse,
    dependencies=[Depends(require_drain_secret)],
)
def drain_jobs(settings: Settings = Depends(get_settings)) -> DrainResponse:
    """Run one bounded drain.

    The caller's view of the outcome is advisory. `pg_net` has a 1-2 second
    default timeout and will routinely record a timeout for a drain that is
    still working - nothing reads this response to decide what happened.
    Progress is guaranteed by the lease, not by the reply (ADR-0007).
    """
    result = drain(
        get_session_factory(),
        max_jobs=settings.drain_max_jobs,
        budget_seconds=settings.drain_budget_seconds,
        lease_seconds=settings.job_lease_seconds,
    )
    return DrainResponse(
        claimed=result.claimed,
        succeeded=result.succeeded,
        failed=result.failed,
        budget_exhausted=result.budget_exhausted,
    )


def require_demo_seed_secret(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.demo_seed_secret
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="demo seed endpoint is not configured",
        )

    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:]

    if not secrets.compare_digest(presented, expected.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing demo seed credentials",
        )


class DemoSeedResponse(BaseModel):
    created: list[str]
    skipped: list[str]


@router.post(
    "/demo/seed",
    response_model=DemoSeedResponse,
    dependencies=[Depends(require_demo_seed_secret)],
)
def seed_demo(session: Session = Depends(session_scope)) -> DemoSeedResponse:
    """Idempotent — safe to call again; already-seeded books are skipped."""
    result = seed_demo_persona(session)
    return DemoSeedResponse(
        created=list(result.created_book_titles), skipped=list(result.skipped_book_titles)
    )
