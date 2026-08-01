"""Pure staleness math for persisted synthesis artifacts (M6, ADR-0013). No
database."""

from __future__ import annotations

from alam.domain.synthesis_staleness import is_artifact_stale


class TestIsArtifactStale:
    def test_not_stale_before_the_ordinal_threshold_is_reached(self) -> None:
        assert (
            is_artifact_stale(
                generated_at_ordinal=5,
                current_ordinal=9,
                ordinal_threshold=5,
                artifact_prompt_version_id="v1",
                current_prompt_version_id="v1",
            )
            is False
        )

    def test_stale_exactly_when_the_ordinal_threshold_is_reached(self) -> None:
        assert (
            is_artifact_stale(
                generated_at_ordinal=5,
                current_ordinal=10,
                ordinal_threshold=5,
                artifact_prompt_version_id="v1",
                current_prompt_version_id="v1",
            )
            is True
        )

    def test_stale_when_the_prompt_version_changed_even_with_no_progress(self) -> None:
        assert (
            is_artifact_stale(
                generated_at_ordinal=5,
                current_ordinal=5,
                ordinal_threshold=5,
                artifact_prompt_version_id="v1",
                current_prompt_version_id="v2",
            )
            is True
        )

    def test_not_stale_with_no_progress_and_an_unchanged_prompt(self) -> None:
        assert (
            is_artifact_stale(
                generated_at_ordinal=5,
                current_ordinal=5,
                ordinal_threshold=5,
                artifact_prompt_version_id="v1",
                current_prompt_version_id="v1",
            )
            is False
        )
