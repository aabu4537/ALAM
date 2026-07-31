"""Diffing between a media item's current structure units and the human's
corrected final list — the merge/split/relabel/exclude step in ADR-0004.

One generic "submit the desired final list" primitive expresses all four
operations without a taxonomy of edit commands: an id omitted from the
desired list is an exclude, two rows collapsing onto one kept id is a merge,
one kept id plus a nearby new (id-less) row is a split, and an unchanged id
with a different label is a relabel. No I/O, no ORM (CLAUDE.md rule 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


class StructurePlanError(ValueError):
    """The desired list is malformed or references a unit that doesn't exist."""


@dataclass(frozen=True, slots=True)
class ExistingUnit:
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class DesiredUnit:
    label: str
    first_lines: str | None = None
    keep_id: uuid.UUID | None = None
    """``None`` means this row is new (a split or a freshly proposed unit).
    Set to an existing unit's id to keep/relabel/reorder it (or to be the
    surviving half of a merge)."""


@dataclass(frozen=True, slots=True)
class UnitToCreate:
    ordinal: int
    label: str
    first_lines: str | None


@dataclass(frozen=True, slots=True)
class UnitToUpdate:
    id: uuid.UUID
    ordinal: int
    label: str
    first_lines: str | None


@dataclass(frozen=True, slots=True)
class StructurePlan:
    to_create: tuple[UnitToCreate, ...]
    to_update: tuple[UnitToUpdate, ...]
    to_delete: tuple[uuid.UUID, ...]


def plan_structure(
    existing: Sequence[ExistingUnit], desired: Sequence[DesiredUnit]
) -> StructurePlan:
    """Ordinals are assigned by position in ``desired`` — 1-based, in order."""
    if not desired:
        raise StructurePlanError("desired structure must contain at least one unit")

    existing_ids = {u.id for u in existing}
    kept_ids = [d.keep_id for d in desired if d.keep_id is not None]

    unknown = set(kept_ids) - existing_ids
    if unknown:
        raise StructurePlanError(
            f"unit ids do not belong to this media item: {sorted(map(str, unknown))}"
        )

    duplicates = {uid for uid in kept_ids if kept_ids.count(uid) > 1}
    if duplicates:
        raise StructurePlanError(
            f"unit ids referenced more than once in the desired list: "
            f"{sorted(map(str, duplicates))}"
        )

    to_create: list[UnitToCreate] = []
    to_update: list[UnitToUpdate] = []
    for ordinal, item in enumerate(desired, start=1):
        if item.keep_id is None:
            to_create.append(
                UnitToCreate(ordinal=ordinal, label=item.label, first_lines=item.first_lines)
            )
        else:
            to_update.append(
                UnitToUpdate(
                    id=item.keep_id,
                    ordinal=ordinal,
                    label=item.label,
                    first_lines=item.first_lines,
                )
            )

    to_delete = tuple(uid for uid in existing_ids if uid not in kept_ids)

    return StructurePlan(
        to_create=tuple(to_create), to_update=tuple(to_update), to_delete=to_delete
    )
