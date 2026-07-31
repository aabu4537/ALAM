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
        template text — not silently."""
        assert PROMPT_VERSION_ID == "extract-memories-v1"
