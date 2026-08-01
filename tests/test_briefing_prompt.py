from __future__ import annotations

from alam.ai.prompts.briefing import PROMPT_VERSION_ID, build_briefing_prompt
from alam.ai.prompts.recommendations import FactForPrompt, MemoryForPrompt


class TestBuildBriefingPrompt:
    def test_includes_book_title_and_author(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune", book_author="Frank Herbert", subjects=[], facts=[], memories=[]
        )

        assert "Dune" in prompt
        assert "Frank Herbert" in prompt

    def test_handles_no_author(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune", book_author=None, subjects=[], facts=[], memories=[]
        )

        assert "Dune" in prompt

    def test_includes_subjects_when_present(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune",
            book_author=None,
            subjects=["Science fiction", "Politics"],
            facts=[],
            memories=[],
        )

        assert "Science fiction" in prompt
        assert "Politics" in prompt

    def test_no_subjects_says_so_explicitly(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune", book_author=None, subjects=[], facts=[], memories=[]
        )

        assert "No catalog subjects are known" in prompt

    def test_includes_every_fact_with_its_id(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune",
            book_author=None,
            subjects=[],
            facts=[FactForPrompt(id="fact-1", statement="prefers unreliable narrators")],
            memories=[],
        )

        assert "id=fact-1" in prompt
        assert "prefers unreliable narrators" in prompt

    def test_includes_every_memory_with_its_id(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune",
            book_author=None,
            subjects=[],
            facts=[],
            memories=[MemoryForPrompt(id="memory-1", content="loved the found-family arc")],
        )

        assert "id=memory-1" in prompt
        assert "loved the found-family arc" in prompt

    def test_handles_no_facts_or_memories(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune", book_author=None, subjects=[], facts=[], memories=[]
        )

        assert "(none recorded yet)" in prompt

    def test_instructs_the_model_not_to_characterize_candidate_content(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune", book_author=None, subjects=[], facts=[], memories=[]
        )

        assert "NOT been given" in prompt

    def test_only_preference_fact_and_memory_are_offered_as_citation_types(self) -> None:
        prompt = build_briefing_prompt(
            book_title="Dune", book_author=None, subjects=[], facts=[], memories=[]
        )

        assert '"preference_fact"' in prompt
        assert '"memory"' in prompt
        assert '"catalog"' not in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently."""
        assert PROMPT_VERSION_ID == "briefing-v1"
