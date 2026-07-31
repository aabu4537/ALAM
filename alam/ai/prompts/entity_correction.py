"""Entity correction prompt (M2 session 2): a post-hoc pass over a raw
transcript, correcting misheard proper nouns against the book's known entity
list (``domain/entity_bias.py``).

Versioned per CLAUDE.md rule 6 — every LLM output records the prompt version
id that produced it. Bump ``PROMPT_VERSION_ID`` on any wording change; do not
edit the template text and keep the old id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "entity-correction-v1"


def build_entity_correction_prompt(*, transcript: str, entities: Sequence[str]) -> str:
    entity_list = ", ".join(entities) if entities else "(none known)"
    return (
        "You are correcting a speech-to-text transcript of a reader's spoken "
        "reflection on a book. The transcript may contain misheard character "
        "names, place names, or invented terms.\n\n"
        f"Known names and terms from this book: {entity_list}\n\n"
        "Fix only clear mishearings of these terms. Do not change wording, "
        "meaning, or tone, and do not add or remove content. If nothing needs "
        "fixing, return the transcript unchanged. Return ONLY the corrected "
        "transcript text, with no preamble or explanation.\n\n"
        f"Transcript:\n{transcript}"
    )
