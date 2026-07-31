"""Pure domain tests — no database, no fixtures.

Uses a real trimmed export of the M1 open-question data: zero review text,
sparse ratings, some rows missing ISBNs entirely. See docs/milestones.md M1.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest

from alam.domain.goodreads import (
    DedupeKey,
    ExistingBook,
    GoodreadsCSVError,
    compute_diff,
    dedupe_key,
    normalize_title_author,
    parse_goodreads_csv,
    row_attributes,
)

HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies"
)


def _row(
    *,
    book_id: str = "1",
    title: str = "East of Eden",
    author: str = "John Steinbeck",
    isbn: str = '="0142000655"',
    isbn13: str = '="9780142000656"',
    rating: str = "0",
    date_read: str = "",
    date_added: str = "2026/06/24",
    shelves: str = "",
    exclusive_shelf: str = "currently-reading",
    review: str = "",
) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow(
        [
            book_id,
            title,
            author,
            "",
            "",
            isbn,
            isbn13,
            rating,
            "Penguin",
            "Paperback",
            "601",
            "2002",
            "1952",
            date_read,
            date_added,
            shelves,
            "",
            exclusive_shelf,
            review,
            "",
            "",
            "1",
            "0",
        ]
    )
    return buf.getvalue().rstrip("\r\n")


def csv_of(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


class TestParsing:
    def test_rejects_a_file_missing_goodreads_columns(self) -> None:
        with pytest.raises(GoodreadsCSVError, match="missing expected"):
            parse_goodreads_csv("a,b,c\n1,2,3")

    def test_strips_the_excel_guard_from_isbns(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row()))

        assert rows[0].isbn == "0142000655"
        assert rows[0].isbn13 == "9780142000656"

    def test_a_rating_of_zero_means_unrated(self) -> None:
        """Goodreads overloads 0 to mean "no rating" rather than a real one."""
        rows = parse_goodreads_csv(csv_of(_row(rating="0")))

        assert rows[0].my_rating is None

    def test_a_real_rating_round_trips(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(rating="3.0")))

        assert rows[0].my_rating == 3

    def test_missing_review_is_none_not_empty_string(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(review="")))

        assert rows[0].my_review is None

    def test_review_text_is_preserved_when_present(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(review="loved the ending")))

        assert rows[0].my_review == "loved the ending"

    def test_missing_isbns_parse_to_none_rather_than_raising(self) -> None:
        """6 of 16 books in the real export have neither ISBN column set."""
        rows = parse_goodreads_csv(csv_of(_row(isbn="", isbn13="")))

        assert rows[0].isbn is None
        assert rows[0].isbn13 is None

    def test_date_added_parses_goodreads_slash_format(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(date_added="2026/06/24")))

        assert rows[0].date_added is not None
        assert rows[0].date_added.isoformat() == "2026-06-24"

    def test_missing_date_read_is_none(self) -> None:
        """Only 2 of 16 books in the real export have Date Read set — most
        rows are `currently-reading` or lack the field entirely."""
        rows = parse_goodreads_csv(csv_of(_row(date_read="")))

        assert rows[0].date_read is None

    def test_shelves_are_split_on_comma(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(shelves="favorites, owned")))

        assert rows[0].bookshelves == ("favorites", "owned")

    def test_no_shelves_is_an_empty_tuple(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(shelves="")))

        assert rows[0].bookshelves == ()


class TestDedupeKey:
    def test_prefers_isbn13_over_everything(self) -> None:
        key = dedupe_key(title="X", author="Y", isbn="0142000655", isbn13="9780142000656")

        assert key == DedupeKey(kind="isbn13", value="9780142000656")

    def test_falls_back_to_isbn10_when_isbn13_is_missing(self) -> None:
        key = dedupe_key(title="X", author="Y", isbn="0142000655", isbn13=None)

        assert key == DedupeKey(kind="isbn10", value="0142000655")

    def test_falls_back_to_title_author_when_no_isbn_exists(self) -> None:
        key = dedupe_key(title="East of Eden", author="John Steinbeck", isbn=None, isbn13=None)

        assert key.kind == "title_author"

    def test_title_author_normalization_ignores_case_and_punctuation(self) -> None:
        assert normalize_title_author("East of Eden!", "John Steinbeck") == normalize_title_author(
            "east of eden", "JOHN STEINBECK"
        )

    def test_title_author_normalization_collapses_whitespace(self) -> None:
        assert normalize_title_author("East  of   Eden", "Steinbeck") == "east of eden steinbeck"


def _existing(
    *, title: str, author: str | None, isbn: str | None, isbn13: str | None, **attrs: object
) -> ExistingBook:
    return ExistingBook(
        id=uuid.uuid4(),
        title=title,
        author=author,
        isbn=isbn,
        isbn13=isbn13,
        attributes={"author": author, "isbn": isbn, "isbn13": isbn13, **attrs},
    )


class TestComputeDiff:
    def test_a_book_with_no_existing_match_is_new(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row()))

        diff = compute_diff(rows, existing=[])

        assert len(diff.to_create) == 1
        assert diff.to_create[0].row.title == "East of Eden"

    def test_an_identical_row_is_unchanged(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row()))
        attrs = row_attributes(rows[0])
        for key in ("author", "isbn", "isbn13"):
            del attrs[key]
        existing = _existing(
            title="East of Eden",
            author="John Steinbeck",
            isbn="0142000655",
            isbn13="9780142000656",
            **attrs,
        )

        diff = compute_diff(rows, existing=[existing])

        assert diff.to_create == ()
        assert diff.to_update == ()
        assert len(diff.unchanged) == 1

    def test_a_changed_rating_is_an_update_not_a_new_book(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(rating="4.0")))
        existing = _existing(
            title="East of Eden",
            author="John Steinbeck",
            isbn="0142000655",
            isbn13="9780142000656",
            my_rating=2,
        )

        diff = compute_diff(rows, existing=[existing])

        assert diff.to_create == ()
        assert len(diff.to_update) == 1
        changed_fields = {c.field for c in diff.to_update[0].changes}
        assert "my_rating" in changed_fields

    def test_matches_by_isbn13_even_if_title_was_edited_in_goodreads(self) -> None:
        """The dedupe key must survive a title correction upstream — matching
        on identity, not on the field that changed."""
        rows = parse_goodreads_csv(csv_of(_row(title="East of Eden (Corrected)")))
        existing = _existing(
            title="East of Eden",
            author="John Steinbeck",
            isbn="0142000655",
            isbn13="9780142000656",
        )

        diff = compute_diff(rows, existing=[existing])

        assert diff.to_create == ()
        assert len(diff.to_update) == 1

    def test_books_with_no_isbn_fall_back_to_title_author_matching(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(isbn="", isbn13="")))
        existing = _existing(title="East of Eden", author="John Steinbeck", isbn=None, isbn13=None)

        diff = compute_diff(rows, existing=[existing])

        assert diff.to_create == ()
        assert len(diff.to_update) == 1 or len(diff.unchanged) == 1

    def test_a_blank_title_row_is_skipped_not_imported(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row(title="")))

        diff = compute_diff(rows, existing=[])

        assert diff.to_create == ()
        assert len(diff.skipped) == 1
        assert diff.skipped[0].reason == "missing title"

    def test_duplicate_rows_within_one_file_are_not_both_created(self) -> None:
        """Guards against two rows sharing a dedupe key silently producing two
        media_items — the fallback title+author key is the case this can
        actually happen for."""
        rows = parse_goodreads_csv(
            csv_of(_row(book_id="1", isbn="", isbn13=""), _row(book_id="2", isbn="", isbn13=""))
        )

        diff = compute_diff(rows, existing=[])

        assert len(diff.to_create) == 1
        assert len(diff.skipped) == 1
        assert "duplicate" in diff.skipped[0].reason

    def test_unrelated_existing_book_is_untouched(self) -> None:
        rows = parse_goodreads_csv(csv_of(_row()))
        other = _existing(
            title="Some Other Book", author="Someone Else", isbn="1111111111", isbn13=None
        )

        diff = compute_diff(rows, existing=[other])

        assert len(diff.to_create) == 1
        assert diff.to_update == ()
        assert diff.unchanged == ()
