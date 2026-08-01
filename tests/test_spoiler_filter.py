"""ADR-0002 Layer 1: pure ordinal containment. No database."""

from __future__ import annotations

from dataclasses import dataclass

from alam.domain.spoiler_filter import filter_visible, is_visible, visible_prediction_status


class TestIsVisible:
    def test_past_ordinal_is_visible(self) -> None:
        assert is_visible(structure_ordinal=3, current_ordinal=5)

    def test_current_ordinal_is_visible(self) -> None:
        """The reader is currently in this unit, not before it."""
        assert is_visible(structure_ordinal=5, current_ordinal=5)

    def test_future_ordinal_is_not_visible(self) -> None:
        assert not is_visible(structure_ordinal=6, current_ordinal=5)

    def test_the_very_first_unit_before_any_progress(self) -> None:
        assert not is_visible(structure_ordinal=1, current_ordinal=0)


@dataclass
class _Item:
    label: str
    structure_ordinal: int


class TestFilterVisible:
    def test_drops_future_items_and_keeps_the_rest(self) -> None:
        items = [_Item("a", 1), _Item("b", 5), _Item("c", 9)]

        result = filter_visible(items, current_ordinal=5)

        assert [item.label for item in result] == ["a", "b"]

    def test_preserves_input_order(self) -> None:
        """A re-check after ranking must not reshuffle the ranking."""
        items = [_Item("c", 2), _Item("a", 1), _Item("b", 2)]

        result = filter_visible(items, current_ordinal=5)

        assert [item.label for item in result] == ["c", "a", "b"]

    def test_empty_input(self) -> None:
        assert filter_visible([], current_ordinal=5) == []

    def test_everything_excluded(self) -> None:
        items = [_Item("a", 10), _Item("b", 11)]

        assert filter_visible(items, current_ordinal=5) == []


class TestVisiblePredictionStatus:
    def test_masks_a_resolved_status_before_the_window_closes(self) -> None:
        """The core re-read hazard (ADR-0012): a prediction resolved during
        an earlier, further-along session must not reveal its real outcome
        to a reader who hasn't reached the window's close this time."""
        status = visible_prediction_status(
            status="confirmed", made_at_ordinal=5, resolution_window=10, current_ordinal=7
        )

        assert status == "pending"

    def test_reveals_the_real_status_exactly_when_the_window_closes(self) -> None:
        status = visible_prediction_status(
            status="confirmed", made_at_ordinal=5, resolution_window=10, current_ordinal=15
        )

        assert status == "confirmed"

    def test_reveals_the_real_status_long_after_the_window_has_closed(self) -> None:
        status = visible_prediction_status(
            status="refuted", made_at_ordinal=5, resolution_window=10, current_ordinal=100
        )

        assert status == "refuted"

    def test_a_still_pending_prediction_stays_pending(self) -> None:
        status = visible_prediction_status(
            status="pending", made_at_ordinal=5, resolution_window=10, current_ordinal=7
        )

        assert status == "pending"

    def test_unresolvable_is_masked_the_same_as_any_other_real_status(self) -> None:
        """ "Unresolvable" is itself information (docs/milestones.md, M5: a
        real outcome, not a failure mode) — it must be masked exactly like
        confirmed/refuted before the window closes."""
        status = visible_prediction_status(
            status="unresolvable", made_at_ordinal=5, resolution_window=10, current_ordinal=7
        )

        assert status == "pending"
