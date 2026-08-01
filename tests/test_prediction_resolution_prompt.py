from __future__ import annotations

from alam.ai.prompts.prediction_resolution import PROMPT_VERSION_ID, build_resolution_prompt


class TestBuildResolutionPrompt:
    def test_includes_the_prediction_statement(self) -> None:
        prompt = build_resolution_prompt(
            prediction_statement="the steward will betray the king", evidence=["x"]
        )

        assert "the steward will betray the king" in prompt

    def test_includes_every_evidence_memory(self) -> None:
        prompt = build_resolution_prompt(
            prediction_statement="x",
            evidence=["the steward turned out to be loyal", "the king was warned in time"],
        )

        assert "the steward turned out to be loyal" in prompt
        assert "the king was warned in time" in prompt

    def test_mentions_every_outcome(self) -> None:
        prompt = build_resolution_prompt(prediction_statement="x", evidence=["y"])

        for outcome in ("confirmed", "refuted", "unresolvable"):
            assert outcome in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently."""
        assert PROMPT_VERSION_ID == "resolve-prediction-v1"
