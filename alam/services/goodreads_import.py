"""Orchestrates a Goodreads CSV import: parse, diff, then optionally apply.

``domain.goodreads`` does the parsing and diffing (pure, no I/O). This module
is the only place that talks to the database for an import, per CLAUDE.md's
dependency direction — routers stay thin, domain stays pure, this is where
they meet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.domain.goodreads import ExistingBook, compute_diff, parse_goodreads_csv
from alam.persistence.models.media_item import MediaType
from alam.persistence.repositories.media_items import MediaItemRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.domain.goodreads import ImportDiff


def preview_import(session: Session, *, user_id: uuid.UUID | None, csv_text: str) -> ImportDiff:
    """Computes the diff without writing anything.

    ``user_id`` is ``None`` when the owner account does not exist yet — that
    is not an error, it just means every row diffs as new.
    """
    rows = parse_goodreads_csv(csv_text)
    existing = _existing_books(session, user_id) if user_id is not None else []
    return compute_diff(rows, existing)


def commit_import(session: Session, *, user_id: uuid.UUID, csv_text: str) -> ImportDiff:
    """Re-parses and applies in one transaction, so what gets written matches
    what a caller would have seen from `preview_import` on the same input.

    There is no server-side preview state to consume — two calls with a file
    that changed in between will disagree, which is an accepted limitation of
    an API-only, pre-frontend flow (M1; a UI would hold the file, not re-post
    it).
    """
    rows = parse_goodreads_csv(csv_text)
    existing = _existing_books(session, user_id)
    diff = compute_diff(rows, existing)

    items = MediaItemRepository(session)

    for new_book in diff.to_create:
        items.create(
            user_id=user_id,
            title=new_book.row.title,
            media_type=MediaType.BOOK,
            attributes=new_book.attributes,
        )

    for updated in diff.to_update:
        item = items.get(updated.existing_id)
        if item is None:
            raise RuntimeError(f"media item {updated.existing_id} vanished mid-import")
        item.title = updated.row.title
        # Merge, not replace: a later EPUB ingestion writes keys of its own
        # into the same attributes blob, and a re-import must not erase them.
        item.attributes = {**item.attributes, **updated.attributes}

    session.flush()
    return diff


def _existing_books(session: Session, user_id: uuid.UUID) -> list[ExistingBook]:
    items = MediaItemRepository(session).list_for_user(user_id, media_type=MediaType.BOOK)
    return [
        ExistingBook(
            id=item.id,
            title=item.title,
            author=item.attributes.get("author"),
            isbn=item.attributes.get("isbn"),
            isbn13=item.attributes.get("isbn13"),
            attributes=item.attributes,
        )
        for item in items
    ]
