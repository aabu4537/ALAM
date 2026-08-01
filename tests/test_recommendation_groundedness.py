"""Pure citation-existence matching for recommendations (M6 session 2,
ADR-0014). No database — id sets are handed in directly."""

from __future__ import annotations

from alam.domain.recommendation_groundedness import CitationCheck, find_ungrounded_citations


class TestFindUngroundedCitations:
    def test_no_citations_means_nothing_ungrounded(self) -> None:
        result = find_ungrounded_citations(
            [], valid_fact_ids=frozenset(), valid_memory_ids=frozenset()
        )

        assert result == []

    def test_a_citation_to_a_real_fact_is_grounded(self) -> None:
        citation = CitationCheck(
            media_item_id="book-1", cites_type="preference_fact", cites_id="fact-1"
        )

        result = find_ungrounded_citations(
            [citation], valid_fact_ids=frozenset({"fact-1"}), valid_memory_ids=frozenset()
        )

        assert result == []

    def test_a_citation_to_a_real_memory_is_grounded(self) -> None:
        citation = CitationCheck(media_item_id="book-1", cites_type="memory", cites_id="memory-1")

        result = find_ungrounded_citations(
            [citation], valid_fact_ids=frozenset(), valid_memory_ids=frozenset({"memory-1"})
        )

        assert result == []

    def test_a_citation_to_a_nonexistent_fact_id_is_ungrounded(self) -> None:
        citation = CitationCheck(
            media_item_id="book-1", cites_type="preference_fact", cites_id="fake-fact"
        )

        result = find_ungrounded_citations(
            [citation], valid_fact_ids=frozenset({"fact-1"}), valid_memory_ids=frozenset()
        )

        assert result == [citation]

    def test_a_fact_id_cited_as_a_memory_is_ungrounded(self) -> None:
        """The valid set for the wrong ``cites_type`` doesn't count — a real
        preference_fact id cited with ``cites_type="memory"`` must still
        fail, since it isn't a real memory id."""
        citation = CitationCheck(media_item_id="book-1", cites_type="memory", cites_id="fact-1")

        result = find_ungrounded_citations(
            [citation], valid_fact_ids=frozenset({"fact-1"}), valid_memory_ids=frozenset()
        )

        assert result == [citation]

    def test_one_bad_citation_among_several_good_ones_is_reported_alone(self) -> None:
        good = CitationCheck(
            media_item_id="book-1", cites_type="preference_fact", cites_id="fact-1"
        )
        bad = CitationCheck(media_item_id="book-2", cites_type="memory", cites_id="fake-memory")

        result = find_ungrounded_citations(
            [good, bad],
            valid_fact_ids=frozenset({"fact-1"}),
            valid_memory_ids=frozenset({"memory-1"}),
        )

        assert result == [bad]
