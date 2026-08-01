"""ADR-0002 Layer 1: pure ordinal containment. No database."""

from __future__ import annotations

from dataclasses import dataclass

from alam.domain.spoiler_filter import filter_visible, is_visible


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
