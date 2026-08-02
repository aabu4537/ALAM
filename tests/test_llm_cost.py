"""Pure LLM cost estimation (M7 session 1). No database, no model in the
loop."""

from __future__ import annotations

from alam.domain.llm_cost import estimate_cost_usd


class TestEstimateCostUsd:
    def test_a_known_anthropic_model_prices_correctly(self) -> None:
        cost = estimate_cost_usd(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        assert cost == 3.00 + 15.00

    def test_an_unknown_anthropic_model_is_unpriceable(self) -> None:
        cost = estimate_cost_usd(
            provider="anthropic",
            model="claude-some-future-model",
            input_tokens=1000,
            output_tokens=1000,
        )

        assert cost is None

    def test_an_unknown_provider_is_unpriceable(self) -> None:
        cost = estimate_cost_usd(
            provider="some-new-vendor", model="whatever", input_tokens=1000, output_tokens=1000
        )

        assert cost is None

    def test_fake_is_always_free_regardless_of_model(self) -> None:
        cost = estimate_cost_usd(
            provider="fake",
            model="anything-at-all",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        assert cost == 0.0

    def test_ollama_is_always_free_regardless_of_model(self) -> None:
        cost = estimate_cost_usd(
            provider="ollama", model="llama3.2:70b", input_tokens=1_000_000, output_tokens=1_000_000
        )

        assert cost == 0.0

    def test_a_missing_provider_is_unpriceable_not_free(self) -> None:
        """A pre-migration row with no ``provider`` recorded — this must
        never be silently treated as free, even though it might have come
        from the fake provider historically; we genuinely don't know."""
        cost = estimate_cost_usd(
            provider=None,
            model="claude-sonnet-4-5-20250929",
            input_tokens=1000,
            output_tokens=1000,
        )

        assert cost is None

    def test_zero_tokens_costs_nothing(self) -> None:
        cost = estimate_cost_usd(
            provider="anthropic",
            model="claude-sonnet-4-5-20250929",
            input_tokens=0,
            output_tokens=0,
        )

        assert cost == 0.0
