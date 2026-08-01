from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from alam.jobs.job_types import RESOLVE_PREDICTIONS, TRANSCRIBE_CAPTURE
from alam.persistence.models.capture import CaptureStatus
from alam.persistence.models.job import Job, JobStatus
from alam.persistence.models.reading_session import ReadingSessionStatus
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.capture_submission import UnknownStructureUnitError, submit_capture
from alam.services.epub_ingestion import UnknownMediaItemError
from alam.services.reading_sessions import UnknownReadingSessionError, end_reading_session

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


class TestReadingSessionRepository:
    def test_first_call_creates_an_active_session(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        repo = ReadingSessionRepository(session)

        reading_session = repo.get_or_create_active(
            book.id, structure_unit_id=chapters[0].id, ordinal=1, progress=1 / 3
        )

        assert reading_session.status is ReadingSessionStatus.ACTIVE
        assert reading_session.current_ordinal == 1

    def test_a_second_call_advances_the_same_session_rather_than_creating_another(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        repo = ReadingSessionRepository(session)
        first = repo.get_or_create_active(
            book.id, structure_unit_id=chapters[0].id, ordinal=1, progress=1 / 3
        )

        second = repo.get_or_create_active(
            book.id, structure_unit_id=chapters[1].id, ordinal=2, progress=2 / 3
        )

        assert second.id == first.id
        assert second.current_ordinal == 2

    def test_ending_a_session_makes_room_for_a_re_read(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        repo = ReadingSessionRepository(session)
        first = repo.get_or_create_active(
            book.id, structure_unit_id=chapters[2].id, ordinal=3, progress=1.0
        )
        repo.end(first, status=ReadingSessionStatus.COMPLETED)

        assert repo.get_active_for_media_item(book.id) is None

        reread = repo.get_or_create_active(
            book.id, structure_unit_id=chapters[0].id, ordinal=1, progress=1 / 3
        )

        assert reread.id != first.id


class TestSubmitCapture:
    def test_creates_a_pending_capture_with_denormalized_ordinal(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[1].id,
            audio=b"fake-audio-bytes",
        )

        assert capture.status is CaptureStatus.PENDING
        assert capture.structure_unit_id == chapters[1].id
        assert capture.structure_ordinal == 2
        assert capture.media_item_id == book.id
        assert capture.audio_data == b"fake-audio-bytes"

    def test_advances_the_books_active_reading_session(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"one",
        )

        reading_session = ReadingSessionRepository(session).get(capture.reading_session_id)
        assert reading_session is not None
        assert reading_session.current_ordinal == 1
        assert reading_session.current_progress == pytest.approx(1 / 3)

    def test_two_captures_in_the_same_book_share_one_reading_session(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        first = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"one",
        )
        second = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[1].id,
            audio=b"two",
        )

        assert first.reading_session_id == second.reading_session_id

    def test_enqueues_a_transcribe_job_in_the_same_transaction(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"one",
        )

        # Not routed through JobQueue.claim() here: Postgres's `now()` is fixed
        # at the start of the outer transaction the `session` fixture opened,
        # which predates this test — `run_after <= now()` could never see a
        # row enqueued mid-test this way. test_job_queue.py exercises claim()
        # properly, against real committed transactions, for exactly this
        # reason; this only needs to confirm the row landed.
        jobs = session.scalars(select(Job).where(Job.job_type == TRANSCRIBE_CAPTURE)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"capture_id": str(capture.id)}
        assert jobs[0].status is JobStatus.PENDING

    def test_also_enqueues_prediction_resolution_for_the_book(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"one",
        )

        jobs = session.scalars(select(Job).where(Job.job_type == RESOLVE_PREDICTIONS)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"media_item_id": str(book.id)}

    def test_unknown_media_item_is_rejected(
        self, session: Session, owner: User, chapters: list[MediaStructureUnit]
    ) -> None:
        with pytest.raises(UnknownMediaItemError):
            submit_capture(
                session,
                user_id=owner.id,
                media_item_id=uuid.uuid4(),
                structure_unit_id=chapters[0].id,
                audio=b"x",
            )

    def test_another_users_book_is_rejected(
        self, session: Session, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        someone_else = UserRepository(session).create(display_name="Someone Else")

        with pytest.raises(UnknownMediaItemError):
            submit_capture(
                session,
                user_id=someone_else.id,
                media_item_id=book.id,
                structure_unit_id=chapters[0].id,
                audio=b"x",
            )

    def test_unknown_structure_unit_is_rejected(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        with pytest.raises(UnknownStructureUnitError):
            submit_capture(
                session,
                user_id=owner.id,
                media_item_id=book.id,
                structure_unit_id=uuid.uuid4(),
                audio=b"x",
            )

    def test_a_structure_unit_from_another_book_is_rejected(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        other_book = MediaItemRepository(session).create(user_id=owner.id, title="Another")
        foreign_unit = StructureUnitRepository(session).create(
            media_item_id=other_book.id, ordinal=1, label="Not this book"
        )

        with pytest.raises(UnknownStructureUnitError):
            submit_capture(
                session,
                user_id=owner.id,
                media_item_id=book.id,
                structure_unit_id=foreign_unit.id,
                audio=b"x",
            )


class TestEndReadingSession:
    def test_marks_completed_with_a_timestamp(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )

        ended = end_reading_session(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            reading_session_id=capture.reading_session_id,
            status=ReadingSessionStatus.COMPLETED,
        )

        assert ended.status is ReadingSessionStatus.COMPLETED
        assert ended.ended_at is not None

    def test_abandoned_is_a_first_class_outcome(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )

        ended = end_reading_session(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            reading_session_id=capture.reading_session_id,
            status=ReadingSessionStatus.ABANDONED,
        )

        assert ended.status is ReadingSessionStatus.ABANDONED

    def test_unknown_session_is_rejected(
        self, session: Session, owner: User, book: MediaItem
    ) -> None:
        with pytest.raises(UnknownReadingSessionError):
            end_reading_session(
                session,
                user_id=owner.id,
                media_item_id=book.id,
                reading_session_id=uuid.uuid4(),
                status=ReadingSessionStatus.COMPLETED,
            )

    def test_a_session_from_a_different_book_is_rejected(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        other_book = MediaItemRepository(session).create(user_id=owner.id, title="Another")
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )

        with pytest.raises(UnknownReadingSessionError):
            end_reading_session(
                session,
                user_id=owner.id,
                media_item_id=other_book.id,
                reading_session_id=capture.reading_session_id,
                status=ReadingSessionStatus.COMPLETED,
            )

    def test_another_users_session_is_rejected(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )
        someone_else = UserRepository(session).create(display_name="Someone Else")

        with pytest.raises(UnknownReadingSessionError):
            end_reading_session(
                session,
                user_id=someone_else.id,
                media_item_id=book.id,
                reading_session_id=capture.reading_session_id,
                status=ReadingSessionStatus.COMPLETED,
            )


class TestCaptureRepository:
    def test_list_for_media_item_is_ordered_by_creation(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        reading_session = ReadingSessionRepository(session).get_or_create_active(
            book.id, structure_unit_id=chapters[0].id, ordinal=1, progress=1 / 3
        )
        first = CaptureRepository(session).create(
            reading_session_id=reading_session.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            structure_ordinal=1,
            audio_data=b"one",
        )
        second = CaptureRepository(session).create(
            reading_session_id=first.reading_session_id,
            media_item_id=book.id,
            structure_unit_id=chapters[1].id,
            structure_ordinal=2,
            audio_data=b"two",
        )

        listed = CaptureRepository(session).list_for_media_item(book.id)

        assert [c.id for c in listed] == [first.id, second.id]

    def test_excluding_a_chapter_with_captures_fails_loudly(
        self, session: Session, owner: User, book: MediaItem, chapters: list[MediaStructureUnit]
    ) -> None:
        """The known limitation documented in ADR-0004's follow-on for M2: a
        chapter that already has a capture against it cannot be silently
        deleted by re-verification's merge/exclude path. No ``ondelete``
        cascade is configured on purpose, so this is an ``IntegrityError``,
        not silent data loss."""
        submit_capture(
            session,
            user_id=owner.id,
            media_item_id=book.id,
            structure_unit_id=chapters[0].id,
            audio=b"x",
        )

        StructureUnitRepository(session).delete(chapters[0])
        with pytest.raises(IntegrityError):
            session.flush()
