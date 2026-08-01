"""``MediaItemRepository``'s catalog-metadata additions (M6 session 3,
ADR-0015): the backfill's cursor query and the write that records a fetch
result, including a real "checked, found nothing" miss.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.users import UserRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import User

pytestmark = pytest.mark.db


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


class TestListMissingCatalogMetadata:
    def test_an_item_with_no_catalog_key_is_returned(self, session: Session, owner: User) -> None:
        repo = MediaItemRepository(session)
        item = repo.create(user_id=owner.id, title="Dune")

        result = repo.list_missing_catalog_metadata(after_id=None, limit=10)

        assert item.id in {i.id for i in result}

    def test_an_item_with_a_catalog_key_is_excluded_even_when_the_fetch_found_nothing(
        self, session: Session, owner: User
    ) -> None:
        repo = MediaItemRepository(session)
        item = repo.create(user_id=owner.id, title="Unfindable Book")
        repo.set_catalog_metadata(
            item, blurb=None, subjects=[], series=None, fetched_at=dt.datetime.now(dt.UTC)
        )

        result = repo.list_missing_catalog_metadata(after_id=None, limit=10)

        assert item.id not in {i.id for i in result}

    def test_the_cursor_excludes_items_at_or_before_after_id(
        self, session: Session, owner: User
    ) -> None:
        repo = MediaItemRepository(session)
        first = repo.create(user_id=owner.id, title="First")
        second = repo.create(user_id=owner.id, title="Second")

        result = repo.list_missing_catalog_metadata(after_id=first.id, limit=10)

        ids = {i.id for i in result}
        assert first.id not in ids
        assert second.id in ids

    def test_limit_bounds_the_batch_size(self, session: Session, owner: User) -> None:
        repo = MediaItemRepository(session)
        for i in range(3):
            repo.create(user_id=owner.id, title=f"Book {i}")

        result = repo.list_missing_catalog_metadata(after_id=None, limit=2)

        assert len(result) == 2


class TestSetCatalogMetadata:
    def test_records_a_found_result_without_erasing_other_attributes(
        self, session: Session, owner: User
    ) -> None:
        repo = MediaItemRepository(session)
        item = repo.create(user_id=owner.id, title="Dune", attributes={"author": "Frank Herbert"})
        fetched_at = dt.datetime.now(dt.UTC)

        updated = repo.set_catalog_metadata(
            item,
            blurb="A desert planet.",
            subjects=["Science fiction"],
            series="Dune",
            fetched_at=fetched_at,
        )

        assert updated.attributes["author"] == "Frank Herbert"
        assert updated.attributes["catalog"]["blurb"] == "A desert planet."
        assert updated.attributes["catalog"]["subjects"] == ["Science fiction"]
        assert updated.attributes["catalog"]["series"] == "Dune"
        assert updated.attributes["catalog"]["fetched_at"] == fetched_at.isoformat()

    def test_records_a_miss_distinctly_from_never_checked(
        self, session: Session, owner: User
    ) -> None:
        repo = MediaItemRepository(session)
        item = repo.create(user_id=owner.id, title="Unfindable Book")

        updated = repo.set_catalog_metadata(
            item, blurb=None, subjects=[], series=None, fetched_at=dt.datetime.now(dt.UTC)
        )

        assert "catalog" in updated.attributes
        assert updated.attributes["catalog"]["blurb"] is None
