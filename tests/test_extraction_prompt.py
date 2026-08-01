from __future__ import annotations

from alam.ai.prompts.extraction import PROMPT_VERSION_ID, build_extraction_prompt


class TestBuildExtractionPrompt:
    def test_includes_the_transcript_verbatim(self) -> None:
        prompt = build_extraction_prompt("I think the steward is lying to the king.")

        assert "I think the steward is lying to the king." in prompt

    def test_mentions_every_fixed_memory_type(self) -> None:
        prompt = build_extraction_prompt("x")

        for memory_type in (
            "prediction",
            "opinion",
            "emotional_reaction",
            "confusion",
            "character_judgment",
            "favorite_moment",
            "meta_comment",
            "other",
        ):
            assert memory_type in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently. Bumped to v2 for the M5.5a follow-up
        rewrite that fixed the category-selection ambiguity Task A found."""
        assert PROMPT_VERSION_ID == "extract-memories-v2"

    def test_states_that_only_applicable_types_are_emitted(self) -> None:
        """The v2 rewrite's whole point: a type not present must not appear
        with a placeholder value — this is what a weak local model got
        wrong in the M5.5a baseline (docs/eval/baseline-local-providers.md's
        follow-up diagnosis)."""
        prompt = build_extraction_prompt("x")

        assert "not a slot you must fill" in prompt
        assert "must not" in prompt and "appear in your output at all" in prompt
