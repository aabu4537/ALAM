from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.domain.goodreads import GoodreadsCSVError
from alam.persistence.models import MediaType
from alam.persistence.repositories import MediaItemRepository, UserRepository
from alam.services.goodreads_import import commit_import, preview_import

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import User

HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies"
)
EDEN_ROW = (
    '1,East of Eden,John Steinbeck,,,="0142000655",="9780142000656",0,'
    "Penguin,Paperback,601,2002,1952,,2026/06/24,,,currently-reading,,,,1,0"
)
FRANKENSTEIN_ROW = (
    '2,Frankenstein: The 1818 Text,Mary Shelley,,,="0143131842",="9780143131847",3.0,'
    "Penguin Classics,Paperback,260,2018,1818,2026/07/31,2026/06/20,,,read,,,,1,0"
)


def csv_of(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


class TestPreview:
    def test_with_no_owner_yet_everything_previews_as_new(self, session: Session) -> None:
        diff = preview_import(session, user_id=None, csv_text=csv_of(EDEN_ROW))

        assert len(diff.to_create) == 1

    def test_does_not_write_anything(self, session: Session, owner: User) -> None:
        preview_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))
        session.flush()

        assert MediaItemRepository(session).list_for_user(owner.id) == []

    def test_a_malformed_file_raises_rather_than_silently_importing_nothing(
        self, session: Session, owner: User
    ) -> None:
        with pytest.raises(GoodreadsCSVError):
            preview_import(session, user_id=owner.id, csv_text="not,a,goodreads,export")

    def test_second_preview_sees_a_book_committed_by_the_first_pass(
        self, session: Session, owner: User
    ) -> None:
        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))

        diff = preview_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))

        assert diff.to_create == ()
        assert len(diff.unchanged) == 1


class TestCommit:
    def test_creates_a_media_item_per_new_book(self, session: Session, owner: User) -> None:
        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW, FRANKENSTEIN_ROW))

        items = MediaItemRepository(session).list_for_user(owner.id)
        assert {i.title for i in items} == {"East of Eden", "Frankenstein: The 1818 Text"}
        assert all(i.media_type is MediaType.BOOK for i in items)

    def test_created_items_carry_goodreads_attributes(self, session: Session, owner: User) -> None:
        commit_import(session, user_id=owner.id, csv_text=csv_of(FRANKENSTEIN_ROW))

        (item,) = MediaItemRepository(session).list_for_user(owner.id)
        assert item.attributes["isbn13"] == "9780143131847"
        assert item.attributes["my_rating"] == 3
        assert item.attributes["exclusive_shelf"] == "read"

    def test_re_running_the_same_file_does_not_duplicate(
        self, session: Session, owner: User
    ) -> None:
        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))
        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))

        items = MediaItemRepository(session).list_for_user(owner.id)
        assert len(items) == 1

    def test_a_changed_field_updates_the_existing_item_in_place(
        self, session: Session, owner: User
    ) -> None:
        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))
        (before,) = MediaItemRepository(session).list_for_user(owner.id)
        before_id = before.id

        upgraded_row = EDEN_ROW.replace(",0,", ",5.0,").replace("currently-reading", "read")
        commit_import(session, user_id=owner.id, csv_text=csv_of(upgraded_row))

        (after,) = MediaItemRepository(session).list_for_user(owner.id)
        assert after.id == before_id, "must update in place, not create a duplicate"
        assert after.attributes["my_rating"] == 5
        assert after.attributes["exclusive_shelf"] == "read"

    def test_re_import_preserves_attributes_it_does_not_own(
        self, session: Session, owner: User
    ) -> None:
        """A stand-in for what EPUB ingestion will later write into the same
        JSONB blob — a re-import must merge, not replace."""
        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))
        (item,) = MediaItemRepository(session).list_for_user(owner.id)
        item.attributes = {**item.attributes, "epub_path": "/books/eden.epub"}
        session.flush()

        commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))

        (after,) = MediaItemRepository(session).list_for_user(owner.id)
        assert after.attributes["epub_path"] == "/books/eden.epub"

    def test_owner_bootstrap_is_idempotent_and_scopes_the_import(self, session: Session) -> None:
        assert UserRepository(session).get_owner() is None

        owner_id = UserRepository(session).get_or_create_owner("Owner").id
        commit_import(session, user_id=owner_id, csv_text=csv_of(EDEN_ROW))

        assert UserRepository(session).get_owner() is not None
        assert len(MediaItemRepository(session).list_for_user(owner_id)) == 1

    def test_a_second_users_books_are_never_touched(self, session: Session, owner: User) -> None:
        other = UserRepository(session).create(display_name="Someone Else")
        MediaItemRepository(session).create(
            user_id=other.id, title="East of Eden", attributes={"author": "John Steinbeck"}
        )

        diff = commit_import(session, user_id=owner.id, csv_text=csv_of(EDEN_ROW))

        assert len(diff.to_create) == 1, "must not match another user's copy of the same book"
        assert len(MediaItemRepository(session).list_for_user(other.id)) == 1
