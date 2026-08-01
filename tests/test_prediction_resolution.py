"""Pure ordinal math for prediction resolution (M5). No database."""

from __future__ import annotations

from alam.domain.prediction_resolution import evidence_window, is_due_for_resolution


class TestIsDueForResolution:
    def test_not_due_before_the_window_closes(self) -> None:
        assert (
            is_due_for_resolution(made_at_ordinal=5, resolution_window=10, current_ordinal=14)
            is False
        )

    def test_due_exactly_when_the_window_closes(self) -> None:
        assert (
            is_due_for_resolution(made_at_ordinal=5, resolution_window=10, current_ordinal=15)
            is True
        )

    def test_still_due_after_the_window_has_long_closed(self) -> None:
        assert (
            is_due_for_resolution(made_at_ordinal=5, resolution_window=10, current_ordinal=100)
            is True
        )


class TestEvidenceWindow:
    def test_excludes_the_ordinal_the_prediction_was_made_at(self) -> None:
        start, _end = evidence_window(made_at_ordinal=5, resolution_window=10)

        assert start == 6

    def test_includes_the_ordinal_the_window_closes_at(self) -> None:
        _start, end = evidence_window(made_at_ordinal=5, resolution_window=10)

        assert end == 15

    def test_a_window_of_one_covers_exactly_the_next_ordinal(self) -> None:
        assert evidence_window(made_at_ordinal=5, resolution_window=1) == (6, 6)
