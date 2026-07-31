from __future__ import annotations

import pytest

from alam.domain.reading_progress import compute_progress


class TestComputeProgress:
    def test_first_chapter_of_one(self) -> None:
        assert compute_progress(1, 1) == 1.0

    def test_midway(self) -> None:
        assert compute_progress(2, 4) == 0.5

    def test_last_chapter_is_one(self) -> None:
        assert compute_progress(10, 10) == 1.0

    def test_first_chapter_of_many_is_a_small_fraction(self) -> None:
        assert compute_progress(1, 10) == pytest.approx(0.1)

    def test_zero_total_units_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            compute_progress(1, 0)

    def test_negative_total_units_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            compute_progress(1, -3)

    def test_an_ordinal_past_the_total_is_clamped_rather_than_erroring(self) -> None:
        """A caller's cached ordinal can momentarily lag a concurrent
        re-verification. Progress is a display value, not the filtering key."""
        assert compute_progress(99, 10) == 1.0
