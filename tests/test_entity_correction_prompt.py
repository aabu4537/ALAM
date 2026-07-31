from __future__ import annotations

from alam.ai.prompts.entity_correction import PROMPT_VERSION_ID, build_entity_correction_prompt


class TestBuildEntityCorrectionPrompt:
    def test_includes_the_transcript_verbatim(self) -> None:
        prompt = build_entity_correction_prompt(
            transcript="I think the mud dib guy is lying.", entities=["Muad'Dib"]
        )

        assert "I think the mud dib guy is lying." in prompt

    def test_includes_every_entity(self) -> None:
        prompt = build_entity_correction_prompt(
            transcript="x", entities=["Muad'Dib", "Arrakis", "Dune"]
        )

        assert "Muad'Dib" in prompt
        assert "Arrakis" in prompt
        assert "Dune" in prompt

    def test_no_entities_still_produces_a_usable_prompt(self) -> None:
        prompt = build_entity_correction_prompt(transcript="x", entities=[])

        assert "x" in prompt
        assert "none known" in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently."""
        assert PROMPT_VERSION_ID == "entity-correction-v1"
