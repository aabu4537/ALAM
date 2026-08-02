"""get_cost_view: aggregating llm_calls into a cost view (M7 session 1).
Seeds rows directly via LLMCallRepository rather than through
InstrumentedLLMProvider — the instrumentation choke point itself is
covered by test_llm_call_instrumentation.py; this tests the aggregation
math."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.persistence.repositories.llm_calls import LLMCallRepository
from alam.services.cost_view import get_cost_view

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def _call(
    session: Session,
    *,
    call_site: str = "alam.services.recommendations._generate",
    provider: str | None = "anthropic",
    model: str = "claude-sonnet-4-5-20250929",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    latency_ms: float = 250.0,
) -> None:
    LLMCallRepository(session).create(
        call_site=call_site,
        provider=provider,
        prompt_version_id="v1",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        job_id=None,
    )


class TestGetCostView:
    def test_empty_llm_calls_produces_a_zeroed_view(self, session: Session) -> None:
        view = get_cost_view(session)

        assert view.total_calls == 0
        assert view.total_cost_usd == 0.0
        assert view.total_unknown_cost_call_count == 0
        assert view.by_model == []
        assert view.by_call_site == []
        assert view.recent_calls == []

    def test_a_single_priceable_call_is_reflected_in_totals(self, session: Session) -> None:
        _call(session, input_tokens=1_000_000, output_tokens=1_000_000)

        view = get_cost_view(session)

        assert view.total_calls == 1
        assert view.total_cost_usd == pytest.approx(18.00)
        assert view.total_unknown_cost_call_count == 0

    def test_two_calls_to_the_same_model_are_grouped(self, session: Session) -> None:
        _call(session, input_tokens=1000, output_tokens=1000)
        _call(session, input_tokens=1000, output_tokens=1000)

        view = get_cost_view(session)

        assert len(view.by_model) == 1
        assert view.by_model[0].calls == 2
        assert view.by_model[0].input_tokens == 2000
        assert view.by_model[0].output_tokens == 2000

    def test_calls_to_different_models_are_grouped_separately(self, session: Session) -> None:
        _call(session, model="claude-sonnet-4-5-20250929")
        _call(session, provider="fake", model="fake-llm-v1")

        view = get_cost_view(session)

        assert len(view.by_model) == 2

    def test_an_unpriceable_call_does_not_null_the_groups_cost(self, session: Session) -> None:
        """A known model plus an unknown one in the same group must still
        report the known portion, not degrade the whole group to
        unpriceable."""
        _call(session, model="claude-sonnet-4-5-20250929", input_tokens=1_000_000, output_tokens=0)
        _call(session, model="claude-some-future-model", input_tokens=1_000_000, output_tokens=0)

        view = get_cost_view(session)

        by_model = {m.model: m for m in view.by_model}
        assert by_model["claude-sonnet-4-5-20250929"].cost_usd == pytest.approx(3.00)
        assert by_model["claude-sonnet-4-5-20250929"].unknown_cost_call_count == 0
        assert by_model["claude-some-future-model"].cost_usd == 0.0
        assert by_model["claude-some-future-model"].unknown_cost_call_count == 1
        assert view.total_unknown_cost_call_count == 1

    def test_a_missing_provider_counts_as_unknown_not_free(self, session: Session) -> None:
        _call(session, provider=None)

        view = get_cost_view(session)

        assert view.total_unknown_cost_call_count == 1
        assert view.total_cost_usd == 0.0

    def test_free_providers_contribute_zero_cost_and_no_unknowns(self, session: Session) -> None:
        _call(
            session,
            provider="ollama",
            model="llama3.2",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        view = get_cost_view(session)

        assert view.total_cost_usd == 0.0
        assert view.total_unknown_cost_call_count == 0

    def test_calls_are_grouped_by_call_site_too(self, session: Session) -> None:
        _call(session, call_site="alam.services.recommendations._generate")
        _call(session, call_site="alam.services.briefing._generate")
        _call(session, call_site="alam.services.recommendations._generate")

        view = get_cost_view(session)

        by_site = {c.call_site: c for c in view.by_call_site}
        assert by_site["alam.services.recommendations._generate"].calls == 2
        assert by_site["alam.services.briefing._generate"].calls == 1

    def test_recent_calls_are_newest_first(self, session: Session) -> None:
        _call(session, call_site="first-call")
        _call(session, call_site="second-call")

        view = get_cost_view(session)

        assert [c.call_site for c in view.recent_calls] == ["second-call", "first-call"]

    def test_totals_include_every_call_even_beyond_the_recent_calls_cap(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lower the cap rather than seeding hundreds of rows — what matters
        is that ``total_calls``/``total_cost_usd`` aggregate over
        everything, while ``recent_calls`` respects the cap."""
        monkeypatch.setattr("alam.services.cost_view.RECENT_CALLS_LIMIT", 2)
        for i in range(5):
            _call(session, call_site=f"call-{i}")

        view = get_cost_view(session)

        assert view.total_calls == 5
        assert len(view.recent_calls) == 2
