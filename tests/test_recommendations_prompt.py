from __future__ import annotations

from alam.ai.prompts.recommendations import (
    PROMPT_VERSION_ID,
    CandidateBook,
    FactForPrompt,
    MemoryForPrompt,
    build_recommendations_prompt,
)


class TestBuildRecommendationsPrompt:
    def test_includes_every_candidate_with_its_id(self) -> None:
        prompt = build_recommendations_prompt(
            candidates=[
                CandidateBook(media_item_id="book-1", title="Dune", author="Frank Herbert"),
                CandidateBook(media_item_id="book-2", title="Neuromancer", author=None),
            ],
            facts=[],
            memories=[],
        )

        assert "id=book-1" in prompt
        assert "Dune" in prompt
        assert "Frank Herbert" in prompt
        assert "id=book-2" in prompt
        assert "Neuromancer" in prompt

    def test_includes_every_fact_with_its_id(self) -> None:
        prompt = build_recommendations_prompt(
            candidates=[],
            facts=[FactForPrompt(id="fact-1", statement="prefers unreliable narrators")],
            memories=[],
        )

        assert "id=fact-1" in prompt
        assert "prefers unreliable narrators" in prompt

    def test_includes_every_memory_with_its_id(self) -> None:
        prompt = build_recommendations_prompt(
            candidates=[],
            facts=[],
            memories=[MemoryForPrompt(id="memory-1", content="loved the found-family arc")],
        )

        assert "id=memory-1" in prompt
        assert "loved the found-family arc" in prompt

    def test_handles_no_candidates_facts_or_memories(self) -> None:
        prompt = build_recommendations_prompt(candidates=[], facts=[], memories=[])

        assert "(none)" in prompt
        assert "(none recorded yet)" in prompt

    def test_instructs_the_model_not_to_characterize_candidate_content(self) -> None:
        prompt = build_recommendations_prompt(candidates=[], facts=[], memories=[])

        assert "NO information" in prompt

    def test_a_candidate_with_no_catalog_data_has_no_known_line(self) -> None:
        prompt = build_recommendations_prompt(
            candidates=[CandidateBook(media_item_id="book-1", title="Dune", author=None)],
            facts=[],
            memories=[],
        )

        # The instructions mention the "Known:" convention generally; what
        # matters is that this specific candidate's own line doesn't carry
        # one, since it has no catalog data.
        assert "\n  Known:" not in prompt

    def test_a_candidate_with_a_blurb_gets_a_known_line(self) -> None:
        prompt = build_recommendations_prompt(
            candidates=[
                CandidateBook(
                    media_item_id="book-1",
                    title="Dune",
                    author=None,
                    blurb="A desert planet and the boy who would rule it.",
                )
            ],
            facts=[],
            memories=[],
        )

        assert "Known:" in prompt
        assert "A desert planet and the boy who would rule it." in prompt

    def test_a_candidate_with_subjects_lists_them_in_the_known_line(self) -> None:
        prompt = build_recommendations_prompt(
            candidates=[
                CandidateBook(
                    media_item_id="book-1",
                    title="Dune",
                    author=None,
                    subjects=["Science fiction", "Politics"],
                )
            ],
            facts=[],
            memories=[],
        )

        assert "Science fiction" in prompt
        assert "Politics" in prompt

    def test_mentions_catalog_as_a_citable_type(self) -> None:
        prompt = build_recommendations_prompt(candidates=[], facts=[], memories=[])

        assert '"catalog"' in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently."""
        assert PROMPT_VERSION_ID == "recommendations-v2"
