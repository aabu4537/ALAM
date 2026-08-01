from __future__ import annotations

from alam.ai.prompts.journey_summary import PROMPT_VERSION_ID, build_journey_summary_prompt


class TestBuildJourneySummaryPrompt:
    def test_includes_the_book_title_and_current_position(self) -> None:
        prompt = build_journey_summary_prompt(
            book_title="Dune", current_ordinal=7, memories=["x"], predictions=["y"]
        )

        assert "Dune" in prompt
        assert "7" in prompt

    def test_includes_every_memory_and_prediction(self) -> None:
        prompt = build_journey_summary_prompt(
            book_title="Dune",
            current_ordinal=7,
            memories=["I love the sandworms"],
            predictions=["I bet Paul becomes emperor"],
        )

        assert "I love the sandworms" in prompt
        assert "I bet Paul becomes emperor" in prompt

    def test_states_a_position_constraint_against_future_content(self) -> None:
        prompt = build_journey_summary_prompt(
            book_title="Dune", current_ordinal=7, memories=[], predictions=[]
        )

        assert "current position" in prompt.lower()
        assert (
            "after the reader" in prompt.lower() or "not use any other knowledge" in prompt.lower()
        )

    def test_handles_no_memories_or_predictions_yet(self) -> None:
        prompt = build_journey_summary_prompt(
            book_title="Dune", current_ordinal=1, memories=[], predictions=[]
        )

        assert "none recorded yet" in prompt
        assert "none made yet" in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently."""
        assert PROMPT_VERSION_ID == "journey-summary-v1"
