"""Pure domain tests — no database, no fixtures, no clock."""

from __future__ import annotations

import pytest

from alam.domain.backoff import backoff_seconds, with_jitter


class TestBackoffSeconds:
    def test_first_retry_waits_the_base_delay(self) -> None:
        assert backoff_seconds(1, base_seconds=2.0) == 2.0

    def test_growth_is_exponential(self) -> None:
        delays = [backoff_seconds(a, base_seconds=2.0, factor=2.0) for a in range(1, 6)]

        assert delays == [2.0, 4.0, 8.0, 16.0, 32.0]

    def test_delay_is_capped(self) -> None:
        """A job failing for a day should still retry hourly, not in weeks."""
        assert backoff_seconds(50, base_seconds=2.0, cap_seconds=3600.0) == 3600.0

    def test_is_monotonic_up_to_the_cap(self) -> None:
        delays = [backoff_seconds(a) for a in range(1, 20)]

        assert delays == sorted(delays)

    def test_attempt_zero_is_rejected(self) -> None:
        """Attempts are 1-based; a zero here means the caller is off by one."""
        with pytest.raises(ValueError, match="must be >= 1"):
            backoff_seconds(0)


class TestJitter:
    def test_never_returns_less_than_half_the_delay(self) -> None:
        """The reason this is equal jitter rather than full jitter — a
        near-zero draw must not retry a failing job almost immediately."""
        assert with_jitter(100.0, 0.0) == 50.0

    def test_never_exceeds_the_delay(self) -> None:
        assert with_jitter(100.0, 0.999) < 100.0

    @pytest.mark.parametrize("draw", [0.0, 0.25, 0.5, 0.75, 0.99])
    def test_stays_within_bounds_across_the_range(self, draw: float) -> None:
        result = with_jitter(60.0, draw)

        assert 30.0 <= result <= 60.0

    def test_draw_outside_the_unit_interval_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\)"):
            with_jitter(10.0, 1.0)
