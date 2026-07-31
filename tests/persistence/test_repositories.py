from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alam.persistence.models import MediaType, StructureUnitType
from alam.persistence.repositories import (
    MediaItemRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, MediaStructureUnit, User


@pytest.fixture
def user(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


@pytest.fixture
def book(session: Session, user: User) -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=user.id,
        title="Pale Fire",
        attributes={"author": "Vladimir Nabokov", "isbn13": "9780679723424"},
    )


@pytest.fixture
def chapters(session: Session, book: MediaItem) -> list[MediaStructureUnit]:
    repo = StructureUnitRepository(session)
    return [
        repo.create(media_item_id=book.id, ordinal=i, label=f"Chapter {i}") for i in range(1, 6)
    ]


class TestUsers:
    def test_create_and_get(self, session: Session) -> None:
        repo = UserRepository(session)
        created = repo.create(display_name="Owner")

        assert repo.get(created.id) == created

    def test_ids_are_uuid7_and_therefore_time_ordered(self, session: Session) -> None:
        """v7 keys sort by creation time, which is why they were chosen over v4 —
        index locality on every table in the system."""
        repo = UserRepository(session)
        ids = [repo.create(display_name=f"u{i}").id for i in range(8)]

        assert ids == sorted(ids)
        assert all(u.version == 7 for u in ids)

    def test_demo_user_is_found_without_the_caller_naming_it(self, session: Session) -> None:
        repo = UserRepository(session)
        repo.create(display_name="Owner", is_demo=False)
        demo = repo.create(display_name="Demo Reader", is_demo=True)

        assert repo.get_demo_user() == demo

    def test_no_demo_user_returns_none_rather_than_the_real_one(self, session: Session) -> None:
        """CLAUDE.md rule 9. If demo mode falls back to a real user when the
        persona is missing, private reading notes become publicly reachable."""
        repo = UserRepository(session)
        repo.create(display_name="Owner", is_demo=False)

        assert repo.get_demo_user() is None


class TestMediaItems:
    def test_attributes_round_trip_as_jsonb(self, session: Session, book: MediaItem) -> None:
        session.expire(book)

        assert book.attributes["author"] == "Vladimir Nabokov"

    def test_defaults_to_book(self, book: MediaItem) -> None:
        assert book.media_type is MediaType.BOOK

    def test_structure_starts_unverified(self, book: MediaItem) -> None:
        """ADR-0004: spine order is a hypothesis. Nothing may be indexed against
        unverified structure, so the default must be the safe one."""
        assert book.structure_verified_at is None
        assert book.structure_is_verified is False

    def test_marking_verified_records_an_aware_timestamp(
        self, session: Session, book: MediaItem
    ) -> None:
        MediaItemRepository(session).mark_structure_verified(book)

        assert book.structure_is_verified is True
        assert book.structure_verified_at is not None
        assert book.structure_verified_at.tzinfo is not None

    def test_listing_is_scoped_to_one_user(self, session: Session, user: User) -> None:
        """The user_id boundary from rule 9, checked at the repository."""
        users = UserRepository(session)
        items = MediaItemRepository(session)
        other = users.create(display_name="Someone else")
        items.create(user_id=user.id, title="Mine")
        items.create(user_id=other.id, title="Theirs")

        assert [i.title for i in items.list_for_user(user.id)] == ["Mine"]

    def test_deleting_an_item_removes_its_structure(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """ADR-0001 flags cascade correctness as a real risk."""
        units = StructureUnitRepository(session)
        MediaItemRepository(session).delete(book)
        session.flush()

        assert units.list_for_media_item(book.id) == []


class TestStructureUnits:
    def test_listed_in_ordinal_order(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        units = StructureUnitRepository(session)

        assert [u.ordinal for u in units.list_for_media_item(book.id)] == [1, 2, 3, 4, 5]

    def test_unit_type_round_trips_as_an_enum(self, session: Session, book: MediaItem) -> None:
        unit = StructureUnitRepository(session).create(
            media_item_id=book.id, ordinal=1, label="Ep 1", unit_type=StructureUnitType.EPISODE
        )
        session.expire(unit)

        assert unit.unit_type is StructureUnitType.EPISODE

    def test_duplicate_ordinal_within_one_item_is_rejected(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        # `create` flushes, so the violation surfaces there rather than at a
        # later explicit flush.
        with pytest.raises(IntegrityError):
            StructureUnitRepository(session).create(
                media_item_id=book.id, ordinal=3, label="Duplicate"
            )

    def test_same_ordinal_in_different_items_is_fine(
        self, session: Session, user: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        other = MediaItemRepository(session).create(user_id=user.id, title="Another")
        StructureUnitRepository(session).create(
            media_item_id=other.id, ordinal=1, label="Chapter 1"
        )

        session.flush()  # must not raise

    def test_spoiler_filter_window(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """ADR-0002 layer 1: `ordinal <= :current`, no join.

        The reader at chapter 3 must not be able to see 4 or 5.
        """
        visible = StructureUnitRepository(session).list_up_to_ordinal(book.id, 3)

        assert [u.ordinal for u in visible] == [1, 2, 3]


class TestRenumbering:
    """ADR-0006 — the behaviour the FK and the deferrable constraint exist for."""

    def test_bulk_shift_does_not_abort_on_a_transient_collision(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """Shifting every chapter up by one — what excluding front matter looks
        like — passes through states where two rows share an ordinal.

        Under an immediate constraint this raises IntegrityError partway.
        """
        units = StructureUnitRepository(session)
        shifted = {u.id: u.ordinal + 1 for u in units.list_for_media_item(book.id)}

        result = units.renumber(book.id, shifted)

        assert [u.ordinal for u in result] == [2, 3, 4, 5, 6]

    def test_reversal_survives_the_intermediate_state(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        units = StructureUnitRepository(session)
        current = units.list_for_media_item(book.id)
        reversed_map = {u.id: 6 - u.ordinal for u in current}

        result = units.renumber(book.id, reversed_map)

        assert [u.label for u in result] == [
            "Chapter 5",
            "Chapter 4",
            "Chapter 3",
            "Chapter 2",
            "Chapter 1",
        ]

    def test_identity_survives_renumbering(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """The whole point of the FK: a stable id through an ordinal change.

        This is what lets a later `memories` row recompute its denormalized
        ordinal instead of silently pointing at the wrong chapter.
        """
        units = StructureUnitRepository(session)
        chapter_two = units.get_by_ordinal(book.id, 2)
        assert chapter_two is not None
        stable_id = chapter_two.id

        units.renumber(book.id, {u.id: u.ordinal + 10 for u in units.list_for_media_item(book.id)})

        moved = units.get(stable_id)
        assert moved is not None
        assert moved.label == "Chapter 2"
        assert moved.ordinal == 12

    def test_recompute_query_repairs_a_stale_denormalized_ordinal(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """Simulates what a `memories` row will do after re-verification.

        Holds an id plus a copy of the ordinal, renumbers, then recomputes —
        the reconciliation ADR-0006 specifies.
        """
        units = StructureUnitRepository(session)
        unit = units.get_by_ordinal(book.id, 4)
        assert unit is not None
        referencing_row = {"structure_unit_id": unit.id, "structure_ordinal": unit.ordinal}

        units.renumber(book.id, {u.id: u.ordinal * 2 for u in units.list_for_media_item(book.id)})

        current = units.get(referencing_row["structure_unit_id"])  # type: ignore[arg-type]
        assert current is not None
        assert referencing_row["structure_ordinal"] != current.ordinal, "should be stale"

        referencing_row["structure_ordinal"] = current.ordinal
        assert referencing_row["structure_ordinal"] == 8

    def test_renumbering_rejects_units_from_another_media_item(
        self, session: Session, user: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        units = StructureUnitRepository(session)
        other = MediaItemRepository(session).create(user_id=user.id, title="Another")
        foreign = units.create(media_item_id=other.id, ordinal=1, label="Not mine")

        with pytest.raises(ValueError, match="do not belong"):
            units.renumber(book.id, {foreign.id: 99})

    def test_renumbering_to_a_duplicate_is_deferred_but_not_discarded(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """Deferring the check must not throw it away.

        Forcing the constraint back to IMMEDIATE is the check that would
        otherwise happen at COMMIT — asserted this way so the outer transaction
        the fixture uses for rollback stays intact.
        """
        units = StructureUnitRepository(session)
        current = units.list_for_media_item(book.id)

        units.renumber(book.id, {current[0].id: 99, current[1].id: 99})

        with pytest.raises(IntegrityError):
            session.execute(
                text("SET CONSTRAINTS uq_media_structure_units_media_item_id_ordinal IMMEDIATE")
            )

    def test_unknown_unit_id_is_rejected(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        units = StructureUnitRepository(session)

        with pytest.raises(ValueError, match="do not belong"):
            units.renumber(book.id, {uuid.uuid4(): 1})
