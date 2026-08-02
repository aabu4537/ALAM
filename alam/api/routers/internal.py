"""Internal operations endpoints.

Not part of the public API. The drain endpoint is the production trigger under
ADR-0007 — Supabase Cron calls it on a schedule — and it is a public URL, so it
requires a shared secret. On a metered free tier an open drain is a billing
problem as much as a correctness one.

The demo seed endpoint is the same shape (public URL, shared secret, fails
closed when unconfigured) for a different reason: it writes data, and an open
write endpoint is a spam vector even though the data it writes is fixed and
harmless.

The embeddings backfill endpoint reuses the drain secret rather than getting
its own. It enqueues jobs, the same blast radius as draining the queue it
enqueues them onto — unlike the demo seed endpoint, it writes nothing a
caller could see or spam beyond what the queue itself already bounds.

The consolidation trigger is the same shape again, same secret: Supabase
Cron calls it weekly (ADR-0001, M4) — the schedule entry itself lives in
Supabase, not in this repo, same as the drain schedule (ADR-0007).

The costs endpoint (M7 session 1) also reuses the drain secret, for a
different reason again: it's read-only, so it isn't a billing or spam
vector, but it's operational spend data on a public URL — the same "not
meant for public consumption" reasoning already applied to writes here,
applied to a read. LLM spend only — see `services/cost_view.py` and
`domain/llm_cost.py` for the scope decision (embeddings/STT aren't
instrumented yet).
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from alam.config.settings import Settings, get_settings
from alam.jobs.job_types import (
    CONSOLIDATE_PREFERENCES,
    EMBED_MEMORIES_BACKFILL,
    FETCH_CATALOG_METADATA,
)
from alam.jobs.queue import JobQueue
from alam.jobs.runner import drain
from alam.persistence.session import get_session_factory, session_scope
from alam.services.cost_view import get_cost_view
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


class EmbeddingBackfillResponse(BaseModel):
    enqueued: bool


@router.post(
    "/embeddings/backfill",
    response_model=EmbeddingBackfillResponse,
    dependencies=[Depends(require_drain_secret)],
)
def trigger_embedding_backfill(
    session: Session = Depends(session_scope),
) -> EmbeddingBackfillResponse:
    """Enqueues the first batch job; the drain schedule does the rest.

    Idempotent to call repeatedly: `list_needing_embedding` only ever selects
    memories still missing an embedding for the current model/version, so a
    second call while one backfill is already in flight — or after it has
    finished — costs one query and enqueues nothing wasteful in the second
    case, and simply resumes coverage in the first (ADR-0008).
    """
    JobQueue(session).enqueue(job_type=EMBED_MEMORIES_BACKFILL, payload={"after_id": None})
    return EmbeddingBackfillResponse(enqueued=True)


class ConsolidationTriggerResponse(BaseModel):
    enqueued: bool


@router.post(
    "/preferences/consolidate",
    response_model=ConsolidationTriggerResponse,
    dependencies=[Depends(require_drain_secret)],
)
def trigger_consolidation(
    session: Session = Depends(session_scope),
) -> ConsolidationTriggerResponse:
    """Enqueues one run starting from whichever user has the oldest
    unconsolidated memory; the job itself finds and chains through every
    other user with a backlog (``services/consolidation.py``).

    Idempotent to call repeatedly: a call while a run is already in flight,
    or after one has finished, costs one query and enqueues nothing
    wasteful in the second case.
    """
    JobQueue(session).enqueue(job_type=CONSOLIDATE_PREFERENCES, payload={"user_id": None})
    return ConsolidationTriggerResponse(enqueued=True)


class CatalogBackfillResponse(BaseModel):
    enqueued: bool


@router.post(
    "/catalog/backfill",
    response_model=CatalogBackfillResponse,
    dependencies=[Depends(require_drain_secret)],
)
def trigger_catalog_backfill(session: Session = Depends(session_scope)) -> CatalogBackfillResponse:
    """Enqueues the first batch job; the drain schedule does the rest (M6
    session 3, ADR-0015).

    Idempotent to call repeatedly: ``list_missing_catalog_metadata`` only
    ever selects media items still missing ``attributes["catalog"]``, so a
    second call while one backfill is already in flight — or after it has
    finished — costs one query and enqueues nothing wasteful in the second
    case, and simply resumes coverage in the first, same shape
    ``trigger_embedding_backfill`` establishes.
    """
    JobQueue(session).enqueue(job_type=FETCH_CATALOG_METADATA, payload={"after_id": None})
    return CatalogBackfillResponse(enqueued=True)


class LLMCallCostResponse(BaseModel):
    id: str
    call_site: str
    provider: str | None
    model: str
    prompt_version_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float | None
    """``None`` means unpriceable — an unrecognized (provider, model) pair,
    or a pre-migration row with no provider recorded. Never silently
    ``0.0``."""
    created_at: str


class ModelCostResponse(BaseModel):
    provider: str | None
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    unknown_cost_call_count: int


class CallSiteCostResponse(BaseModel):
    call_site: str
    calls: int
    cost_usd: float
    unknown_cost_call_count: int


class CostViewResponse(BaseModel):
    total_calls: int
    total_cost_usd: float
    total_unknown_cost_call_count: int
    by_model: list[ModelCostResponse]
    by_call_site: list[CallSiteCostResponse]
    recent_calls: list[LLMCallCostResponse]


@router.get(
    "/costs",
    response_model=CostViewResponse,
    dependencies=[Depends(require_drain_secret)],
)
def get_costs(session: Session = Depends(session_scope)) -> CostViewResponse:
    """Per-request token accounting and an aggregate cost view (M7 session
    1, `docs/milestones.md`) — LLM spend only, see the module docstring.
    `recent_calls` is capped (`services.cost_view.RECENT_CALLS_LIMIT`); the
    totals and per-model/per-call-site breakdowns are not.
    """
    view = get_cost_view(session)
    return CostViewResponse(
        total_calls=view.total_calls,
        total_cost_usd=view.total_cost_usd,
        total_unknown_cost_call_count=view.total_unknown_cost_call_count,
        by_model=[
            ModelCostResponse(
                provider=m.provider,
                model=m.model,
                calls=m.calls,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
                cost_usd=m.cost_usd,
                unknown_cost_call_count=m.unknown_cost_call_count,
            )
            for m in view.by_model
        ],
        by_call_site=[
            CallSiteCostResponse(
                call_site=c.call_site,
                calls=c.calls,
                cost_usd=c.cost_usd,
                unknown_cost_call_count=c.unknown_cost_call_count,
            )
            for c in view.by_call_site
        ],
        recent_calls=[
            LLMCallCostResponse(
                id=str(c.id),
                call_site=c.call_site,
                provider=c.provider,
                model=c.model,
                prompt_version_id=c.prompt_version_id,
                input_tokens=c.input_tokens,
                output_tokens=c.output_tokens,
                latency_ms=c.latency_ms,
                cost_usd=c.cost_usd,
                created_at=c.created_at.isoformat(),
            )
            for c in view.recent_calls
        ],
    )
