from __future__ import annotations

from alam.ai.prompts.leak_check import PROMPT_VERSION_ID, build_leak_check_prompt


class TestBuildLeakCheckPrompt:
    def test_includes_the_draft(self) -> None:
        prompt = build_leak_check_prompt(draft="a short summary", excluded_content=["x"])

        assert "a short summary" in prompt

    def test_includes_every_excluded_statement(self) -> None:
        prompt = build_leak_check_prompt(
            draft="x",
            excluded_content=["the steward betrays the king", "the castle falls"],
        )

        assert "the steward betrays the king" in prompt
        assert "the castle falls" in prompt

    def test_handles_no_excluded_content(self) -> None:
        prompt = build_leak_check_prompt(draft="x", excluded_content=[])

        assert "(none)" in prompt

    def test_prompt_version_id_is_stable(self) -> None:
        """Rule 6: every LLM output records the prompt version that produced
        it. If this changes, it must change deliberately, alongside the
        template text — not silently."""
        assert PROMPT_VERSION_ID == "leak-check-v1"
