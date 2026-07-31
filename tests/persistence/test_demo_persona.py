from __future__ import annotations

from typing import TYPE_CHECKING

from alam.persistence.models.capture import CaptureStatus
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    UserRepository,
)
from alam.services.demo_persona import DEMO_LIBRARY, get_demo_library, seed_demo_persona

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestSeedDemoPersona:
    def test_creates_a_demo_flagged_user(self, session: Session) -> None:
        result = seed_demo_persona(session)

        assert result.user.is_demo is True

    def test_creates_one_book_per_seed_entry(self, session: Session) -> None:
        result = seed_demo_persona(session)

        assert len(result.created_book_titles) == len(DEMO_LIBRARY)
        assert result.skipped_book_titles == ()

    def test_never_touches_the_owner(self, session: Session) -> None:
        owner = UserRepository(session).create(display_name="Owner")

        seed_demo_persona(session)

        assert MediaItemRepository(session).list_for_user(owner.id) == []

    def test_at_least_one_book_ships_with_verified_structure(self, session: Session) -> None:
        """Demonstrates the ADR-0004 pipeline end-to-end with demo data,
        without needing a real EPUB file."""
        result = seed_demo_persona(session)

        books = MediaItemRepository(session).list_for_user(result.user.id)
        assert any(b.structure_is_verified for b in books)

    def test_re_seeding_is_idempotent(self, session: Session) -> None:
        first = seed_demo_persona(session)
        second = seed_demo_persona(session)

        assert second.created_book_titles == ()
        assert set(second.skipped_book_titles) == set(first.created_book_titles)
        assert second.user.id == first.user.id

    def test_re_seeding_does_not_duplicate_books(self, session: Session) -> None:
        result = seed_demo_persona(session)
        seed_demo_persona(session)

        books = MediaItemRepository(session).list_for_user(result.user.id)
        assert len(books) == len(DEMO_LIBRARY)

    def test_at_least_one_book_ships_with_an_extracted_memory(self, session: Session) -> None:
        """Demonstrates the M2 capture -> transcribe -> correct -> extract
        pipeline end-to-end with demo data, without real audio or a network
        call — the same role ``test_at_least_one_book_ships_with_verified_
        structure`` plays for ADR-0004."""
        result = seed_demo_persona(session)

        books = MediaItemRepository(session).list_for_user(result.user.id)
        captures = [
            c for book in books for c in CaptureRepository(session).list_for_media_item(book.id)
        ]
        assert captures
        assert all(c.status is CaptureStatus.EXTRACTED for c in captures)

        memories = [
            m for book in books for m in MemoryRepository(session).list_for_media_item(book.id)
        ]
        assert memories

    def test_re_seeding_does_not_duplicate_the_demo_capture(self, session: Session) -> None:
        result = seed_demo_persona(session)
        seed_demo_persona(session)

        books = MediaItemRepository(session).list_for_user(result.user.id)
        captures = [
            c for book in books for c in CaptureRepository(session).list_for_media_item(book.id)
        ]
        assert len(captures) == 1


class TestGetDemoLibrary:
    def test_before_seeding_reports_unseeded_rather_than_erroring(self, session: Session) -> None:
        library = get_demo_library(session)

        assert library.seeded is False
        assert library.persona is None
        assert library.books == ()

    def test_after_seeding_lists_every_book(self, session: Session) -> None:
        seed_demo_persona(session)

        library = get_demo_library(session)

        assert library.seeded is True
        assert len(library.books) == len(DEMO_LIBRARY)

    def test_reports_chapter_counts_for_verified_books(self, session: Session) -> None:
        seed_demo_persona(session)

        library = get_demo_library(session)

        verified = [b for b in library.books if b.structure_verified]
        assert verified
        assert all(b.chapter_count > 0 for b in verified)

    def test_never_lists_the_owners_books(self, session: Session) -> None:
        owner_repo = UserRepository(session)
        owner = owner_repo.create(display_name="Owner")
        MediaItemRepository(session).create(user_id=owner.id, title="Owner's Private Book")

        seed_demo_persona(session)
        library = get_demo_library(session)

        assert all(b.title != "Owner's Private Book" for b in library.books)
