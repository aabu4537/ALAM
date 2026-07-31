"""Pure Goodreads CSV parsing and import diffing.

No I/O, no ORM (CLAUDE.md rule 3) — parsing an in-memory string and diffing it
against plain data is computation, not I/O, so it belongs here rather than in
``services/``.

Goodreads exports vary wildly in how populated they are. This project's own
export has review text on 0 of 16 books and a rating on only 10 — see the open
question in ``docs/milestones.md`` M1. Every field below except title and
author is therefore optional, and nothing downstream may assume review text,
a rating, or even an ISBN exists.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping, Sequence


class GoodreadsCSVError(ValueError):
    """The uploaded file is missing columns a Goodreads export always has."""


REQUIRED_COLUMNS = frozenset({"Title", "Author", "Book Id"})


@dataclass(frozen=True, slots=True)
class GoodreadsRow:
    goodreads_book_id: str
    title: str
    author: str
    isbn: str | None
    isbn13: str | None
    my_rating: int | None
    exclusive_shelf: str | None
    bookshelves: tuple[str, ...]
    date_added: date | None
    date_read: date | None
    my_review: str | None
    number_of_pages: int | None
    publisher: str | None
    year_published: int | None
    original_publication_year: int | None
    read_count: int | None


def parse_goodreads_csv(csv_text: str) -> list[GoodreadsRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
        raise GoodreadsCSVError(
            f"missing expected Goodreads export columns {sorted(REQUIRED_COLUMNS)} — "
            "is this a Goodreads 'Export Library' file?"
        )
    return [_parse_row(row) for row in reader]


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _strip_excel_guard(value: str | None) -> str | None:
    """Goodreads wraps ISBNs as ``="1234567890"`` so Excel doesn't eat leading
    zeros or coerce them to numbers. Strip the guard, not the digits."""
    cleaned = _clean(value)
    if cleaned is None:
        return None
    if cleaned.startswith('="') and cleaned.endswith('"'):
        cleaned = cleaned[2:-1]
    return cleaned or None


def _parse_int(value: str | None) -> int | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_rating(value: str | None) -> int | None:
    # Goodreads uses 0 to mean "not rated", not a real rating.
    rating = _parse_int(value)
    return rating if rating else None


def _parse_date(value: str | None) -> date | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return date.fromisoformat(cleaned.replace("/", "-"))
    except ValueError:
        return None


def _parse_shelves(value: str | None) -> tuple[str, ...]:
    cleaned = _clean(value)
    if cleaned is None:
        return ()
    return tuple(s.strip() for s in cleaned.split(",") if s.strip())


def _parse_row(row: dict[str, str]) -> GoodreadsRow:
    return GoodreadsRow(
        goodreads_book_id=(row.get("Book Id") or "").strip(),
        title=(row.get("Title") or "").strip(),
        author=(row.get("Author") or "").strip(),
        isbn=_strip_excel_guard(row.get("ISBN")),
        isbn13=_strip_excel_guard(row.get("ISBN13")),
        my_rating=_parse_rating(row.get("My Rating")),
        exclusive_shelf=_clean(row.get("Exclusive Shelf")),
        bookshelves=_parse_shelves(row.get("Bookshelves")),
        date_added=_parse_date(row.get("Date Added")),
        date_read=_parse_date(row.get("Date Read")),
        my_review=_clean(row.get("My Review")),
        number_of_pages=_parse_int(row.get("Number of Pages")),
        publisher=_clean(row.get("Publisher")),
        year_published=_parse_int(row.get("Year Published")),
        original_publication_year=_parse_int(row.get("Original Publication Year")),
        read_count=_parse_int(row.get("Read Count")),
    )


def row_attributes(row: GoodreadsRow) -> dict[str, Any]:
    """The subset of ``media_items.attributes`` this import owns.

    Applied as a merge on top of whatever is already there (services layer),
    not a replace — a later EPUB ingestion writes keys of its own into the
    same JSONB blob and must not be clobbered by a re-import.
    """
    return {
        "goodreads_book_id": row.goodreads_book_id,
        "author": row.author,
        "isbn": row.isbn,
        "isbn13": row.isbn13,
        "my_rating": row.my_rating,
        "exclusive_shelf": row.exclusive_shelf,
        "bookshelves": list(row.bookshelves),
        "date_added": row.date_added.isoformat() if row.date_added else None,
        "date_read": row.date_read.isoformat() if row.date_read else None,
        "my_review": row.my_review,
        "number_of_pages": row.number_of_pages,
        "publisher": row.publisher,
        "year_published": row.year_published,
        "original_publication_year": row.original_publication_year,
        "read_count": row.read_count,
    }


DedupeKeyKind = Literal["isbn13", "isbn10", "title_author"]


@dataclass(frozen=True, slots=True)
class DedupeKey:
    kind: DedupeKeyKind
    value: str


def normalize_title_author(title: str, author: str) -> str:
    text = unicodedata.normalize("NFKD", f"{title} {author}".lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def dedupe_key(*, title: str, author: str, isbn: str | None, isbn13: str | None) -> DedupeKey:
    """ISBN13 first, then ISBN10, then normalized title+author — the order the
    M1 DoD specifies. Not an ISBN10<->13 conversion: whichever identifier the
    row actually has wins, and title+author is the fallback of last resort for
    the rows (6 of 16 in this project's own export) that have neither.
    """
    if isbn13:
        return DedupeKey(kind="isbn13", value=isbn13)
    if isbn:
        return DedupeKey(kind="isbn10", value=isbn)
    return DedupeKey(kind="title_author", value=normalize_title_author(title, author))


def row_dedupe_key(row: GoodreadsRow) -> DedupeKey:
    return dedupe_key(title=row.title, author=row.author, isbn=row.isbn, isbn13=row.isbn13)


@dataclass(frozen=True, slots=True)
class ExistingBook:
    """Plain-data view of a ``MediaItem`` the diff needs. No ORM import."""

    id: uuid.UUID
    title: str
    author: str | None
    isbn: str | None
    isbn13: str | None
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    old: Any
    new: Any


@dataclass(frozen=True, slots=True)
class NewBook:
    row: GoodreadsRow
    dedupe_key: DedupeKey
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UpdatedBook:
    existing_id: uuid.UUID
    row: GoodreadsRow
    dedupe_key: DedupeKey
    attributes: dict[str, Any]
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True)
class UnchangedBook:
    existing_id: uuid.UUID
    row: GoodreadsRow
    dedupe_key: DedupeKey


@dataclass(frozen=True, slots=True)
class SkippedRow:
    row_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class ImportDiff:
    to_create: tuple[NewBook, ...]
    to_update: tuple[UpdatedBook, ...]
    unchanged: tuple[UnchangedBook, ...]
    skipped: tuple[SkippedRow, ...]


def _diff_attributes(old: Mapping[str, Any], new: Mapping[str, Any]) -> tuple[FieldChange, ...]:
    changes = [
        FieldChange(field=field_name, old=old.get(field_name), new=new_value)
        for field_name, new_value in new.items()
        if old.get(field_name) != new_value
    ]
    return tuple(changes)


def compute_diff(rows: Sequence[GoodreadsRow], existing: Sequence[ExistingBook]) -> ImportDiff:
    existing_by_key: dict[DedupeKey, ExistingBook] = {}
    for book in existing:
        key = dedupe_key(
            title=book.title, author=book.author or "", isbn=book.isbn, isbn13=book.isbn13
        )
        existing_by_key[key] = book

    to_create: list[NewBook] = []
    to_update: list[UpdatedBook] = []
    unchanged: list[UnchangedBook] = []
    skipped: list[SkippedRow] = []
    seen_keys: set[DedupeKey] = set()

    for index, row in enumerate(rows):
        if not row.title:
            skipped.append(SkippedRow(row_index=index, reason="missing title"))
            continue

        key = row_dedupe_key(row)
        if key in seen_keys:
            skipped.append(
                SkippedRow(
                    row_index=index,
                    reason=f"duplicate of an earlier row in this file (matched by {key.kind})",
                )
            )
            continue
        seen_keys.add(key)

        attributes = row_attributes(row)
        match = existing_by_key.get(key)

        if match is None:
            to_create.append(NewBook(row=row, dedupe_key=key, attributes=attributes))
            continue

        changes = _diff_attributes(match.attributes, attributes)
        if changes:
            to_update.append(
                UpdatedBook(
                    existing_id=match.id,
                    row=row,
                    dedupe_key=key,
                    attributes=attributes,
                    changes=changes,
                )
            )
        else:
            unchanged.append(UnchangedBook(existing_id=match.id, row=row, dedupe_key=key))

    return ImportDiff(
        to_create=tuple(to_create),
        to_update=tuple(to_update),
        unchanged=tuple(unchanged),
        skipped=tuple(skipped),
    )
