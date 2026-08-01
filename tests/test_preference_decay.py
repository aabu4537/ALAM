"""ADR-0001's confidence math: exponential decay, asymptotic reinforcement.
No database."""

from __future__ import annotations

import datetime as dt

import pytest

from alam.domain.preference_decay import HALF_LIFE_DAYS, effective_confidence, reinforce


class TestEffectiveConfidence:
    def test_no_elapsed_time_is_undecayed(self) -> None:
        now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

        result = effective_confidence(base_confidence=0.8, last_reinforced_at=now, now=now)

        assert result == pytest.approx(0.8)

    def test_one_half_life_halves_confidence(self) -> None:
        last_reinforced_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        now = last_reinforced_at + dt.timedelta(days=HALF_LIFE_DAYS)

        result = effective_confidence(
            base_confidence=0.8, last_reinforced_at=last_reinforced_at, now=now
        )

        assert result == pytest.approx(0.4)

    def test_two_half_lives_quarters_confidence(self) -> None:
        last_reinforced_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        now = last_reinforced_at + dt.timedelta(days=2 * HALF_LIFE_DAYS)

        result = effective_confidence(
            base_confidence=0.8, last_reinforced_at=last_reinforced_at, now=now
        )

        assert result == pytest.approx(0.2)

    def test_never_decays_to_exactly_zero(self) -> None:
        """A fact is never fully forgotten, just faded — matches ADR-0001's
        "nothing is deleted" stance carried into the confidence itself."""
        last_reinforced_at = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
        now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

        result = effective_confidence(
            base_confidence=0.8, last_reinforced_at=last_reinforced_at, now=now
        )

        assert result > 0.0


class TestReinforce:
    def test_increments_observation_count(self) -> None:
        _, count = reinforce(base_confidence=0.5, observation_count=3)

        assert count == 4

    def test_moves_confidence_toward_one(self) -> None:
        new_confidence, _ = reinforce(base_confidence=0.5, observation_count=0)

        assert new_confidence > 0.5

    def test_never_reaches_or_exceeds_one(self) -> None:
        confidence = 0.999999
        count = 0
        for _ in range(1000):
            confidence, count = reinforce(base_confidence=confidence, observation_count=count)

        assert confidence < 1.0

    def test_later_reinforcements_move_a_smaller_step(self) -> None:
        """Diminishing returns: the same starting confidence, reinforced with
        a higher existing observation_count, should move less."""
        early_confidence, _ = reinforce(base_confidence=0.5, observation_count=0)
        late_confidence, _ = reinforce(base_confidence=0.5, observation_count=50)

        early_step = early_confidence - 0.5
        late_step = late_confidence - 0.5
        assert late_step < early_step
