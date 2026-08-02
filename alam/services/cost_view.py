"""LLM cost aggregation (M7 session 1) — the "cost view" half, and the
per-call list that's the "per-request" half, of `docs/milestones.md`'s
"Observability: per-request token accounting, cost view" bullet. One
service, one endpoint (`GET /internal/costs`), one milestone item.

LLM-only — see `alam/domain/llm_cost.py`'s module docstring for the scope
decision. Reads `llm_calls` directly (`LLMCallRepository.list_all()`, dev/
personal scale, same "small enough to load wholesale" precedent
`preference_facts`' L3 tier already uses) and computes cost in Python,
since the pricing table is Python-side, not something SQL can join against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.domain.llm_cost import estimate_cost_usd
from alam.persistence.repositories.llm_calls import LLMCallRepository

if TYPE_CHECKING:
    import datetime as dt
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.persistence.models.llm_call import LLMCall

RECENT_CALLS_LIMIT = 200
"""How many of the newest calls the "per-request" list carries. The
aggregates below always cover every row, regardless of this limit."""


@dataclass(frozen=True)
class CallCost:
    id: uuid.UUID
    call_site: str
    provider: str | None
    model: str
    prompt_version_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float | None
    """``None`` means unpriceable — see `domain/llm_cost.py`. Never
    silently `0.0`."""
    created_at: dt.datetime


@dataclass(frozen=True)
class ModelCost:
    provider: str | None
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    """Sum of only the *priceable* calls in this group — one unpriceable
    call doesn't null the whole group's cost, it's counted separately in
    `unknown_cost_call_count` instead, so partial information stays
    visible rather than degrading to nothing."""
    unknown_cost_call_count: int


@dataclass(frozen=True)
class CallSiteCost:
    call_site: str
    calls: int
    cost_usd: float
    unknown_cost_call_count: int


@dataclass(frozen=True)
class CostView:
    total_calls: int
    total_cost_usd: float
    total_unknown_cost_call_count: int
    by_model: list[ModelCost]
    by_call_site: list[CallSiteCost]
    recent_calls: list[CallCost]


@dataclass
class _RunningTotal:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    unknown_cost_call_count: int = 0


def get_cost_view(session: Session) -> CostView:
    calls = LLMCallRepository(session).list_all()  # newest first
    call_costs = [_to_call_cost(c) for c in calls]

    by_model = _aggregate_by_model(call_costs)
    by_call_site = _aggregate_by_call_site(call_costs)

    return CostView(
        total_calls=len(call_costs),
        total_cost_usd=sum(m.cost_usd for m in by_model),
        total_unknown_cost_call_count=sum(m.unknown_cost_call_count for m in by_model),
        by_model=by_model,
        by_call_site=by_call_site,
        recent_calls=call_costs[:RECENT_CALLS_LIMIT],
    )


def _to_call_cost(call: LLMCall) -> CallCost:
    return CallCost(
        id=call.id,
        call_site=call.call_site,
        provider=call.provider,
        model=call.model,
        prompt_version_id=call.prompt_version_id,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        latency_ms=call.latency_ms,
        cost_usd=estimate_cost_usd(
            provider=call.provider,
            model=call.model,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
        ),
        created_at=call.created_at,
    )


def _aggregate_by_model(call_costs: Sequence[CallCost]) -> list[ModelCost]:
    totals: dict[tuple[str | None, str], _RunningTotal] = {}
    for c in call_costs:
        key = (c.provider, c.model)
        running = totals.setdefault(key, _RunningTotal())
        running.calls += 1
        running.input_tokens += c.input_tokens
        running.output_tokens += c.output_tokens
        if c.cost_usd is None:
            running.unknown_cost_call_count += 1
        else:
            running.cost_usd += c.cost_usd

    results = [
        ModelCost(
            provider=provider,
            model=model,
            calls=running.calls,
            input_tokens=running.input_tokens,
            output_tokens=running.output_tokens,
            cost_usd=running.cost_usd,
            unknown_cost_call_count=running.unknown_cost_call_count,
        )
        for (provider, model), running in totals.items()
    ]
    return sorted(results, key=lambda m: (-m.cost_usd, -m.calls))


def _aggregate_by_call_site(call_costs: Sequence[CallCost]) -> list[CallSiteCost]:
    totals: dict[str, _RunningTotal] = {}
    for c in call_costs:
        running = totals.setdefault(c.call_site, _RunningTotal())
        running.calls += 1
        if c.cost_usd is None:
            running.unknown_cost_call_count += 1
        else:
            running.cost_usd += c.cost_usd

    results = [
        CallSiteCost(
            call_site=call_site,
            calls=running.calls,
            cost_usd=running.cost_usd,
            unknown_cost_call_count=running.unknown_cost_call_count,
        )
        for call_site, running in totals.items()
    ]
    return sorted(results, key=lambda c: (-c.cost_usd, -c.calls))
