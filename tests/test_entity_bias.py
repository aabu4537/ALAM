from __future__ import annotations

from alam.domain.entity_bias import book_entity_list


class TestBookEntityList:
    def test_title_author_and_chapters_in_order(self) -> None:
        entities = book_entity_list(
            title="Dune",
            author="Frank Herbert",
            chapter_labels=["Part One: Dune", "Part Two: Muad'Dib"],
        )

        assert entities == ["Dune", "Frank Herbert", "Part One: Dune", "Part Two: Muad'Dib"]

    def test_no_author_is_skipped_rather_than_included_as_none(self) -> None:
        entities = book_entity_list(title="Dune", author=None, chapter_labels=["Chapter 1"])

        assert entities == ["Dune", "Chapter 1"]

    def test_no_chapters_yet_still_returns_title_and_author(self) -> None:
        entities = book_entity_list(title="Dune", author="Frank Herbert", chapter_labels=[])

        assert entities == ["Dune", "Frank Herbert"]

    def test_duplicates_across_title_author_and_chapters_are_collapsed(self) -> None:
        entities = book_entity_list(
            title="Dune", author="Dune", chapter_labels=["Dune", "Chapter 1"]
        )

        assert entities == ["Dune", "Chapter 1"]

    def test_empty_string_labels_are_skipped(self) -> None:
        entities = book_entity_list(title="Dune", author=None, chapter_labels=["", "Chapter 1"])

        assert entities == ["Dune", "Chapter 1"]
