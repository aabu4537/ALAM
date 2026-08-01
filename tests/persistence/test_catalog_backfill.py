"""``fetch_catalog_metadata_backfill`` (M6 session 3, ADR-0015): resumable,
cursor-based, same test shapes ``test_embedding_backfill.py`` establishes
for the embeddings version.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.providers.fakes import ProviderError
from alam.catalog.fakes import FakeCatalogProvider
from alam.catalog.provider import CatalogMetadata
from alam.config.settings import get_settings
from alam.jobs.job_types import FETCH_CATALOG_METADATA
from alam.persistence.models.job import Job
from alam.persistence.repositories import MediaItemRepository, UserRepository
from alam.services.catalog_backfill import fetch_catalog_metadata_backfill

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


class TestFetchCatalogMetadataBackfill:
    def test_fetches_and_persists_metadata_for_every_item_in_one_batch(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        media_items = MediaItemRepository(session)
        book = media_items.create(user_id=owner.id, title="Dune")
        fake = FakeCatalogProvider(
            responses=[CatalogMetadata(blurb="A desert planet.", subjects=["Sci-fi"], series=None)]
        )
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})

        refreshed = media_items.get(book.id)
        assert refreshed is not None
        assert refreshed.attributes["catalog"]["blurb"] == "A desert planet."
        assert refreshed.attributes["catalog"]["subjects"] == ["Sci-fi"]

    def test_a_provider_miss_is_recorded_as_a_real_not_found_result(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        media_items = MediaItemRepository(session)
        book = media_items.create(user_id=owner.id, title="Unfindable Book")
        fake = FakeCatalogProvider(responses=[None])
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})

        refreshed = media_items.get(book.id)
        assert refreshed is not None
        assert refreshed.attributes["catalog"]["blurb"] is None

    def test_a_second_call_does_not_re_fetch_already_covered_items(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        media_items = MediaItemRepository(session)
        media_items.create(user_id=owner.id, title="Dune")
        fake = FakeCatalogProvider()
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})
        fetch_catalog_metadata_backfill(session, {"after_id": None})

        assert len(fake.calls) == 1  # the second run found nothing left to fetch

    def test_resumes_from_the_cursor_rather_than_the_start(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        media_items = MediaItemRepository(session)
        first = media_items.create(user_id=owner.id, title="First")
        second = media_items.create(user_id=owner.id, title="Second")
        fake = FakeCatalogProvider()
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": str(first.id)})

        refreshed_first = media_items.get(first.id)
        refreshed_second = media_items.get(second.id)
        assert refreshed_first is not None
        assert refreshed_second is not None
        assert "catalog" not in refreshed_first.attributes
        assert "catalog" in refreshed_second.attributes

    def test_a_full_batch_chains_the_next_one(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALAM_CATALOG_BACKFILL_BATCH_SIZE", "2")
        get_settings.cache_clear()
        media_items = MediaItemRepository(session)
        seeded = [media_items.create(user_id=owner.id, title=f"Book {i}") for i in range(3)]
        fake = FakeCatalogProvider()
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})

        jobs = session.scalars(select(Job).where(Job.job_type == FETCH_CATALOG_METADATA)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"after_id": str(seeded[1].id)}

    def test_a_short_batch_does_not_chain(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALAM_CATALOG_BACKFILL_BATCH_SIZE", "10")
        get_settings.cache_clear()
        media_items = MediaItemRepository(session)
        media_items.create(user_id=owner.id, title="Dune")
        fake = FakeCatalogProvider()
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})

        jobs = session.scalars(select(Job).where(Job.job_type == FETCH_CATALOG_METADATA)).all()
        assert jobs == []

    def test_no_items_missing_metadata_is_a_no_op(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeCatalogProvider()
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})  # must not raise

        assert fake.calls == []

    def test_provider_failure_propagates_for_the_runner_to_record(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        MediaItemRepository(session).create(user_id=owner.id, title="Dune")
        fake = FakeCatalogProvider(fail_with=ProviderError("catalog is down"))
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        with pytest.raises(ProviderError):
            fetch_catalog_metadata_backfill(session, {"after_id": None})

    def test_author_is_passed_through_from_attributes(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        media_items = MediaItemRepository(session)
        media_items.create(user_id=owner.id, title="Dune", attributes={"author": "Frank Herbert"})
        fake = FakeCatalogProvider()
        monkeypatch.setattr("alam.services.catalog_backfill.get_catalog_provider", lambda: fake)

        fetch_catalog_metadata_backfill(session, {"after_id": None})

        assert fake.calls[0].title == "Dune"
        assert fake.calls[0].author == "Frank Herbert"
