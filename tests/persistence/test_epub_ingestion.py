from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from alam.domain.structure_review import DesiredUnit, StructurePlanError
from alam.media.books.epub import EpubParseError
from alam.persistence.repositories import MediaItemRepository, UserRepository
from alam.services.epub_ingestion import UnknownMediaItemError, commit_epub
from alam.services.structure_verification import verify_structure
from tests.epub_builder import build_epub

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


class TestCommitEpub:
    def test_creates_a_new_media_item_from_epub_metadata(
        self, session: Session, owner: User
    ) -> None:
        item, units = commit_epub(
            session,
            user_id=owner.id,
            media_item_id=None,
            data=build_epub(title="Dune", author="Frank Herbert"),
        )

        assert item.title == "Dune"
        assert item.attributes["author"] == "Frank Herbert"
        assert item.user_id == owner.id
        assert len(units) == 2

    def test_structure_starts_unverified(self, session: Session, owner: User) -> None:
        item, _ = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        assert item.structure_is_verified is False

    def test_units_persist_in_spine_order(self, session: Session, owner: User) -> None:
        _, units = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        assert [u.ordinal for u in units] == [1, 2]
        assert units[0].label == "Chapter One"

    def test_attaches_to_an_existing_media_item_when_given_an_id(
        self, session: Session, owner: User
    ) -> None:
        existing = MediaItemRepository(session).create(user_id=owner.id, title="Placeholder")

        item, units = commit_epub(
            session, user_id=owner.id, media_item_id=existing.id, data=build_epub()
        )

        assert item.id == existing.id
        assert len(units) == 2

    def test_unknown_media_item_id_is_rejected(self, session: Session, owner: User) -> None:
        with pytest.raises(UnknownMediaItemError):
            commit_epub(session, user_id=owner.id, media_item_id=uuid.uuid4(), data=build_epub())

    def test_cannot_attach_to_another_users_book(self, session: Session, owner: User) -> None:
        other = UserRepository(session).create(display_name="Someone Else")
        theirs = MediaItemRepository(session).create(user_id=other.id, title="Not yours")

        with pytest.raises(UnknownMediaItemError):
            commit_epub(session, user_id=owner.id, media_item_id=theirs.id, data=build_epub())

    def test_malformed_epub_raises_before_writing_anything(
        self, session: Session, owner: User
    ) -> None:
        with pytest.raises(EpubParseError):
            commit_epub(session, user_id=owner.id, media_item_id=None, data=b"not an epub")

        assert MediaItemRepository(session).list_for_user(owner.id) == []

    def test_re_ingesting_replaces_the_structure_and_resets_verification(
        self, session: Session, owner: User
    ) -> None:
        item, first_units = commit_epub(
            session, user_id=owner.id, media_item_id=None, data=build_epub()
        )
        verify_structure(
            session,
            media_item_id=item.id,
            user_id=owner.id,
            desired=[DesiredUnit(keep_id=u.id, label=u.label) for u in first_units],
        )
        assert item.structure_is_verified is True

        three_chapters = build_epub(
            chapter_htmls=[
                "<html><body><h1>A</h1><p>a</p></body></html>",
                "<html><body><h1>B</h1><p>b</p></body></html>",
                "<html><body><h1>C</h1><p>c</p></body></html>",
            ]
        )
        item_again, new_units = commit_epub(
            session, user_id=owner.id, media_item_id=item.id, data=three_chapters
        )

        assert item_again.id == item.id
        assert item_again.structure_is_verified is False
        assert len(new_units) == 3
        assert {u.id for u in first_units}.isdisjoint({u.id for u in new_units})


class TestVerifyStructure:
    def test_marks_the_item_verified(self, session: Session, owner: User) -> None:
        item, units = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        verified_item, _ = verify_structure(
            session,
            media_item_id=item.id,
            user_id=owner.id,
            desired=[DesiredUnit(keep_id=u.id, label=u.label) for u in units],
        )

        assert verified_item.structure_is_verified is True

    def test_relabeling_a_unit_persists_the_new_label(self, session: Session, owner: User) -> None:
        item, units = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        _, corrected = verify_structure(
            session,
            media_item_id=item.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=units[0].id, label="Prologue"),
                DesiredUnit(keep_id=units[1].id, label=units[1].label),
            ],
        )

        assert corrected[0].label == "Prologue"

    def test_excluding_a_unit_deletes_it(self, session: Session, owner: User) -> None:
        item, units = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        _, corrected = verify_structure(
            session,
            media_item_id=item.id,
            user_id=owner.id,
            desired=[DesiredUnit(keep_id=units[1].id, label=units[1].label)],
        )

        assert len(corrected) == 1
        assert corrected[0].ordinal == 1

    def test_splitting_a_unit_adds_a_new_one(self, session: Session, owner: User) -> None:
        item, units = commit_epub(
            session,
            user_id=owner.id,
            media_item_id=None,
            data=build_epub(
                chapter_htmls=["<html><body><h1>Long Chapter</h1><p>text</p></body></html>"]
            ),
        )

        _, corrected = verify_structure(
            session,
            media_item_id=item.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=units[0].id, label="Part 1"),
                DesiredUnit(label="Part 2"),
            ],
        )

        assert [u.label for u in corrected] == ["Part 1", "Part 2"]
        assert [u.ordinal for u in corrected] == [1, 2]

    def test_unverified_units_survive_the_deferred_renumber_on_reorder(
        self, session: Session, owner: User
    ) -> None:
        """Reordering is exactly the ADR-0006 bulk-collision case: two units
        swapping ordinals passes through a transient duplicate."""
        item, units = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        _, corrected = verify_structure(
            session,
            media_item_id=item.id,
            user_id=owner.id,
            desired=[
                DesiredUnit(keep_id=units[1].id, label=units[1].label),
                DesiredUnit(keep_id=units[0].id, label=units[0].label),
            ],
        )

        assert [u.id for u in corrected] == [units[1].id, units[0].id]

    def test_unknown_media_item_is_rejected(self, session: Session, owner: User) -> None:
        with pytest.raises(UnknownMediaItemError):
            verify_structure(
                session,
                media_item_id=uuid.uuid4(),
                user_id=owner.id,
                desired=[DesiredUnit(label="X")],
            )

    def test_a_keep_id_from_another_book_is_rejected(self, session: Session, owner: User) -> None:
        _item_a, units_a = commit_epub(
            session, user_id=owner.id, media_item_id=None, data=build_epub()
        )
        item_b, _ = commit_epub(session, user_id=owner.id, media_item_id=None, data=build_epub())

        with pytest.raises(StructurePlanError):
            verify_structure(
                session,
                media_item_id=item_b.id,
                user_id=owner.id,
                desired=[DesiredUnit(keep_id=units_a[0].id, label="Wrong book")],
            )
