"""Pure EPUB-parsing tests — no database, no fixtures."""

from __future__ import annotations

import pytest

from alam.media.books.epub import EpubParseError, parse_epub
from tests.epub_builder import build_epub


class TestMetadata:
    def test_title_and_author_are_read_from_the_opf(self) -> None:
        parsed = parse_epub(build_epub(title="Dune", author="Frank Herbert"))

        assert parsed.metadata.title == "Dune"
        assert parsed.metadata.author == "Frank Herbert"

    def test_missing_title_and_author_parse_to_none(self) -> None:
        parsed = parse_epub(build_epub(title=None, author=None))

        assert parsed.metadata.title is None
        assert parsed.metadata.author is None


class TestSpineOrder:
    def test_units_are_proposed_in_spine_order_starting_at_one(self) -> None:
        parsed = parse_epub(build_epub())

        assert [u.ordinal for u in parsed.units] == [1, 2]

    def test_non_linear_items_are_excluded_from_the_proposal(self) -> None:
        parsed = parse_epub(build_epub(non_linear_indices=frozenset({2})))

        assert len(parsed.units) == 1

    def test_an_epub_with_no_chapters_is_rejected(self) -> None:
        with pytest.raises(EpubParseError, match="manifest is empty"):
            parse_epub(build_epub(chapter_htmls=[]))

    def test_a_spine_left_empty_by_exclusion_is_rejected(self) -> None:
        """A manifest can be non-empty while the spine still ends up empty —
        every item marked non-linear leaves nothing to propose a structure
        from, a distinct failure from an empty manifest."""
        with pytest.raises(EpubParseError, match="spine is empty"):
            parse_epub(
                build_epub(
                    chapter_htmls=["<html><body><p>front matter</p></body></html>"],
                    non_linear_indices=frozenset({1}),
                )
            )


class TestLabelAndPreview:
    def test_label_is_guessed_from_the_first_heading(self) -> None:
        parsed = parse_epub(build_epub())

        assert parsed.units[0].label == "Chapter One"
        assert parsed.units[1].label == "Chapter Two"

    def test_missing_heading_falls_back_to_a_positional_label(self) -> None:
        parsed = parse_epub(
            build_epub(chapter_htmls=["<html><body><p>No heading here.</p></body></html>"])
        )

        assert parsed.units[0].label == "Chapter 1"

    def test_first_lines_strips_tags_and_carries_real_text(self) -> None:
        parsed = parse_epub(build_epub())

        assert parsed.units[0].first_lines is not None
        assert "dark and stormy night" in parsed.units[0].first_lines
        assert "<" not in parsed.units[0].first_lines

    def test_malformed_chapter_markup_degrades_rather_than_raising(self) -> None:
        """ADR-0004: the proposal is a hypothesis. One broken chapter file must
        not abort ingestion of the whole book."""
        parsed = parse_epub(
            build_epub(chapter_htmls=["<html><body><h1>Unclosed<p>oops</body></html>"])
        )

        assert len(parsed.units) == 1
        assert parsed.units[0].label  # some label, parsing did not raise


class TestContainerValidation:
    def test_not_a_zip_file_is_rejected(self) -> None:
        with pytest.raises(EpubParseError, match="not a valid EPUB"):
            parse_epub(b"this is not a zip file at all")

    def test_missing_container_xml_is_rejected(self) -> None:
        with pytest.raises(EpubParseError, match=r"container\.xml"):
            parse_epub(build_epub(include_container=False))
