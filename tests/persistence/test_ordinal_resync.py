"""Structure re-verification (ADR-0004) can renumber a unit that a reading
session, capture, or memory has already denormalized an ordinal from
(CLAUDE.md rule 1). ``services/structure_plan.py`` is the one place that
repairs this — these tests exercise it end to end, through the real
``verify_structure`` service, not just the repository-level resync methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.domain.structure_review import DesiredUnit
from alam.persistence.repositories import (
    MediaItemRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.capture_submission import submit_capture
from alam.services.structure_verification import verify_structure

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, MediaStructureUnit, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(user_id=owner.id, title="Dune")


@pytest.fixture
def chapters(session: Session, book: MediaItem) -> list[MediaStructureUnit]:
    repo = StructureUnitRepository(session)
    return [repo.create(media_item_id=book.id, ordinal=i, label=f"Chapter {i}") for i in (1, 2, 3)]


class TestReorderResync:
    def test_reversing_the_order_updates_the_reading_sessions_ordinal(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[2].id,
            audio=b"x",
        )
        reading_session = ReadingSessionRepository(session).get(capture.reading_session_id)
        assert reading_session is not None
        assert reading_session.current_ordinal == 3

        verify_structure(
            session,
            media_item_id=book.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=chapters[2].id, label=chapters[2].label),
                DesiredUnit(keep_id=chapters[1].id, label=chapters[1].label),
                DesiredUnit(keep_id=chapters[0].id, label=chapters[0].label),
            ],
        )

        session.refresh(reading_session)
        assert reading_session.current_ordinal == 1
        assert reading_session.current_progress == pytest.approx(1 / 3)

    def test_reversing_the_order_updates_the_captures_ordinal(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )
        assert capture.structure_ordinal == 1

        verify_structure(
            session,
            media_item_id=book.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=chapters[2].id, label=chapters[2].label),
                DesiredUnit(keep_id=chapters[1].id, label=chapters[1].label),
                DesiredUnit(keep_id=chapters[0].id, label=chapters[0].label),
            ],
        )

        session.refresh(capture)
        assert capture.structure_ordinal == 3

    def test_reversing_the_order_updates_a_memorys_ordinal(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )
        memory = MemoryRepository(session).create_many(
            capture_id=capture.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            structure_ordinal=1,
            prompt_version_id="extract-memories-v1",
            extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content="x")],
        )[0]

        verify_structure(
            session,
            media_item_id=book.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=chapters[2].id, label=chapters[2].label),
                DesiredUnit(keep_id=chapters[1].id, label=chapters[1].label),
                DesiredUnit(keep_id=chapters[0].id, label=chapters[0].label),
            ],
        )

        session.refresh(memory)
        assert memory.structure_ordinal == 3

    def test_relabeling_without_reordering_leaves_ordinals_untouched(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[1].id,
            audio=b"x",
        )

        verify_structure(
            session,
            media_item_id=book.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=chapters[0].id, label=chapters[0].label),
                DesiredUnit(keep_id=chapters[1].id, label="Renamed Chapter"),
                DesiredUnit(keep_id=chapters[2].id, label=chapters[2].label),
            ],
        )

        session.refresh(capture)
        assert capture.structure_ordinal == 2


class TestExcludingAReferencedUnitFailsLoudly:
    """The documented M2 limitation: no repoint-on-merge/exclude logic exists
    yet, so a chapter that already has a session, capture, or memory against
    it cannot be excluded — the FK's lack of an ``ondelete`` cascade turns
    that into a loud ``IntegrityError`` instead of silent data loss."""

    def test_excluding_a_chapter_with_a_reading_session_fails(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )

        with pytest.raises(IntegrityError):
            verify_structure(
                session,
                media_item_id=book.id,
                user_id=owner.id,
                desired=[
                    DesiredUnit(keep_id=chapters[1].id, label=chapters[1].label),
                    DesiredUnit(keep_id=chapters[2].id, label=chapters[2].label),
                ],
            )
