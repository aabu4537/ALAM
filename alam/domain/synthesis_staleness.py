"""Pure staleness checks for persisted synthesis artifacts (M6, ADR-0013,
ADR-0014).

No I/O — testable in milliseconds, per CLAUDE.md rule 3. Every M6 artifact
type gets a staleness check shaped for what "cached and still current" means
for it — ``is_artifact_stale`` for book-scoped, ordinal-progress artifacts
(journey summaries, later briefings); ``is_recommendation_set_stale`` for
library-wide artifacts with no ordinal (recommendations), where a set of
candidates or facts either changed or didn't. ADR-0013 is explicit this is
tuned per type as each is built, not forced into one shared numeric shape.
"""

from __future__ import annotations


def is_artifact_stale(
    *,
    generated_at_ordinal: int,
    current_ordinal: int,
    ordinal_threshold: int,
    artifact_prompt_version_id: str,
    current_prompt_version_id: str,
) -> bool:
    """True once the reader's progress has advanced far enough past the
    ordinal this artifact was generated at, or once the prompt that would
    generate it has changed — either way, the cached row no longer reflects
    what generating fresh right now would produce."""
    return (
        current_ordinal - generated_at_ordinal >= ordinal_threshold
        or artifact_prompt_version_id != current_prompt_version_id
    )


def is_recommendation_set_stale(
    *,
    generated_shelf_snapshot: frozenset[str],
    current_shelf_snapshot: frozenset[str],
    generated_fact_snapshot: frozenset[str],
    current_fact_snapshot: frozenset[str],
    artifact_prompt_version_id: str,
    current_prompt_version_id: str,
) -> bool:
    """Set-equality, not a threshold — there's no ordinal to throttle
    against here, and no reason to: any change to the to-read shelf (a
    cached row may reference a candidate no longer on it) or to the
    reader's active preference facts (the taste profile it was matched
    against no longer exists as generated) is worth reflecting on the next
    read, unlike ordinal progress within one reading session."""
    return (
        generated_shelf_snapshot != current_shelf_snapshot
        or generated_fact_snapshot != current_fact_snapshot
        or artifact_prompt_version_id != current_prompt_version_id
    )
