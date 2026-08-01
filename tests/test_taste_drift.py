"""Grouping facts into supersede chains. No database."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from alam.domain.taste_drift import group_into_chains


@dataclass
class _Fact:
    label: str
    supersedes_label: str | None
    id: uuid.UUID = None  # type: ignore[assignment]
    supersedes_id: uuid.UUID | None = None


def _facts(*specs: tuple[str, str | None]) -> list[_Fact]:
    """Builds facts with real ids, wiring supersedes_id by label so tests
    stay readable without hand-rolling UUIDs."""
    facts = [
        _Fact(label=label, supersedes_label=supersedes_label, id=uuid.uuid4())
        for label, supersedes_label in specs
    ]
    by_label = {f.label: f for f in facts}
    for fact in facts:
        if fact.supersedes_label is not None:
            parent = by_label.get(fact.supersedes_label)
            fact.supersedes_id = parent.id if parent is not None else uuid.uuid4()
    return facts


def _labels(chains: list[list[_Fact]]) -> list[list[str]]:
    return [[fact.label for fact in chain] for chain in chains]


class TestGroupIntoChains:
    def test_a_single_unsuperseded_fact_is_its_own_chain(self) -> None:
        facts = _facts(("a", None))

        assert _labels(group_into_chains(facts)) == [["a"]]

    def test_a_linear_chain_is_ordered_oldest_to_newest(self) -> None:
        facts = _facts(("v1", None), ("v2", "v1"), ("v3", "v2"))

        assert _labels(group_into_chains(facts)) == [["v1", "v2", "v3"]]

    def test_two_independent_chains_stay_separate(self) -> None:
        facts = _facts(("a1", None), ("b1", None), ("a2", "a1"))

        chains = _labels(group_into_chains(facts))

        assert ["a1", "a2"] in chains
        assert ["b1"] in chains
        assert len(chains) == 2

    def test_input_order_within_a_chain_does_not_matter(self) -> None:
        facts = _facts(("v3", "v2"), ("v1", None), ("v2", "v1"))

        chains = group_into_chains(facts)

        assert [f.label for f in chains[-1]] == ["v1", "v2", "v3"]

    def test_empty_input(self) -> None:
        assert group_into_chains([]) == []

    def test_a_dangling_supersedes_id_not_in_the_input_is_treated_as_a_root(self) -> None:
        """Defensive: every fact ``list_all_for_user`` returns belongs to one
        user, so this shouldn't happen in practice, but a fact whose parent
        wasn't included must not crash the grouping."""
        facts = _facts(("orphan", "missing-parent"))

        assert _labels(group_into_chains(facts)) == [["orphan"]]
