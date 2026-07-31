"""Pure domain tests — no database, no fixtures."""

from __future__ import annotations

import uuid

import pytest

from alam.domain.structure_review import (
    DesiredUnit,
    ExistingUnit,
    StructurePlanError,
    plan_structure,
)


def _uuids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


class TestFreshProposal:
    def test_all_new_units_are_created_in_order(self) -> None:
        desired = [DesiredUnit(label="Ch 1"), DesiredUnit(label="Ch 2"), DesiredUnit(label="Ch 3")]

        plan = plan_structure(existing=[], desired=desired)

        assert [c.ordinal for c in plan.to_create] == [1, 2, 3]
        assert plan.to_update == ()
        assert plan.to_delete == ()

    def test_an_empty_desired_list_is_rejected(self) -> None:
        with pytest.raises(StructurePlanError, match="at least one unit"):
            plan_structure(existing=[], desired=[])


class TestRelabel:
    def test_kept_id_with_a_new_label_is_an_update_not_a_create(self) -> None:
        (unit_id,) = _uuids(1)
        existing = [ExistingUnit(id=unit_id)]
        desired = [DesiredUnit(keep_id=unit_id, label="Corrected Title")]

        plan = plan_structure(existing, desired)

        assert plan.to_create == ()
        assert len(plan.to_update) == 1
        assert plan.to_update[0].id == unit_id
        assert plan.to_update[0].label == "Corrected Title"
        assert plan.to_delete == ()


class TestExclude:
    def test_an_id_omitted_from_desired_is_deleted(self) -> None:
        front_matter, chapter_one = _uuids(2)
        existing = [ExistingUnit(id=front_matter), ExistingUnit(id=chapter_one)]
        desired = [DesiredUnit(keep_id=chapter_one, label="Chapter 1")]

        plan = plan_structure(existing, desired)

        assert plan.to_delete == (front_matter,)
        assert len(plan.to_update) == 1


class TestMerge:
    def test_two_existing_ids_collapsing_onto_one_kept_id_deletes_the_other(self) -> None:
        keep, absorbed = _uuids(2)
        existing = [ExistingUnit(id=keep), ExistingUnit(id=absorbed)]
        desired = [DesiredUnit(keep_id=keep, label="Merged Chapter")]

        plan = plan_structure(existing, desired)

        assert plan.to_delete == (absorbed,)
        assert len(plan.to_update) == 1
        assert plan.to_update[0].id == keep


class TestSplit:
    def test_one_kept_id_plus_a_new_row_produces_one_update_and_one_create(self) -> None:
        (original,) = _uuids(1)
        existing = [ExistingUnit(id=original)]
        desired = [
            DesiredUnit(keep_id=original, label="Chapter 1a"),
            DesiredUnit(label="Chapter 1b"),
        ]

        plan = plan_structure(existing, desired)

        assert len(plan.to_update) == 1
        assert plan.to_update[0].ordinal == 1
        assert len(plan.to_create) == 1
        assert plan.to_create[0].ordinal == 2
        assert plan.to_delete == ()


class TestReorder:
    def test_ordinals_follow_position_in_the_desired_list_not_original_order(self) -> None:
        first, second = _uuids(2)
        existing = [ExistingUnit(id=first), ExistingUnit(id=second)]
        desired = [
            DesiredUnit(keep_id=second, label="Now First"),
            DesiredUnit(keep_id=first, label="Now Second"),
        ]

        plan = plan_structure(existing, desired)

        by_id = {u.id: u.ordinal for u in plan.to_update}
        assert by_id[second] == 1
        assert by_id[first] == 2


class TestValidation:
    def test_a_keep_id_not_in_existing_is_rejected(self) -> None:
        (real,) = _uuids(1)
        foreign = uuid.uuid4()
        existing = [ExistingUnit(id=real)]
        desired = [DesiredUnit(keep_id=foreign, label="Not mine")]

        with pytest.raises(StructurePlanError, match="do not belong"):
            plan_structure(existing, desired)

    def test_the_same_keep_id_referenced_twice_is_rejected(self) -> None:
        (unit_id,) = _uuids(1)
        existing = [ExistingUnit(id=unit_id)]
        desired = [
            DesiredUnit(keep_id=unit_id, label="Copy A"),
            DesiredUnit(keep_id=unit_id, label="Copy B"),
        ]

        with pytest.raises(StructurePlanError, match="more than once"):
            plan_structure(existing, desired)
