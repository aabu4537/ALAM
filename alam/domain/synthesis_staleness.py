"""Pure staleness check for persisted synthesis artifacts (M6, ADR-0013).

No I/O — testable in milliseconds, per CLAUDE.md rule 3. Shared by every M6
artifact type (journey summaries first; recommendations and briefings reuse
it unchanged), same reasoning ``domain/prediction_resolution.py`` gives for
pulling threshold math out of the service and testing it in isolation.
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
