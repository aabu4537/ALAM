"""Recommendations prompt (M6 session 2): pick the reader's own to-read
shelf candidates worth surfacing, backed by their own preference facts and
memories.

Instructs the model to select, not describe — cite specific fact/memory ids
for each candidate rather than writing anything new. This instruction is
not what makes a book-content characterization impossible, though: the
response schema (``ai/synthesis/recommendations.py``) has no field for one
to occupy regardless of what the model attempts, the same caveat ADR-0013
already states for Layer 2 ("nothing stops a model from ignoring the
instruction") applied to why the real enforcement lives in the schema, not
here.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "recommendations-v1"

MAX_RECOMMENDATIONS = 5
"""Requested in the prompt text, not enforced by the schema — the model may
return fewer if fewer candidates genuinely match."""


@dataclass(frozen=True)
class CandidateBook:
    media_item_id: str
    title: str
    author: str | None


@dataclass(frozen=True)
class FactForPrompt:
    id: str
    statement: str


@dataclass(frozen=True)
class MemoryForPrompt:
    id: str
    content: str


def build_recommendations_prompt(
    *,
    candidates: Sequence[CandidateBook],
    facts: Sequence[FactForPrompt],
    memories: Sequence[MemoryForPrompt],
) -> str:
    """``candidates`` are the reader's own to-read shelf — title/author
    only, no plot or theme metadata exists yet (``CatalogProvider`` is a
    later session). ``facts``/``memories`` are the reader's own recorded
    taste evidence, each tagged with its id for citation."""
    candidates_block = (
        "\n".join(
            f'- id={c.media_item_id}: "{c.title}"' + (f" by {c.author}" if c.author else "")
            for c in candidates
        )
        or "(none)"
    )
    facts_block = "\n".join(f"- id={f.id}: {f.statement}" for f in facts) or "(none recorded yet)"
    memories_block = (
        "\n".join(f"- id={m.id}: {m.content}" for m in memories) or "(none recorded yet)"
    )

    lines = [
        "A reader has these books on their to-read shelf, each with an id:",
        "",
        candidates_block,
        "",
        "Here is everything known about the reader's taste, each entry tagged with its id:",
        "",
        "Preference facts (consolidated observations about their taste):",
        facts_block,
        "",
        "Memories (their own recorded reflections while reading other books):",
        memories_block,
        "",
        f"Select up to {MAX_RECOMMENDATIONS} of the shelf candidates that best "
        "match the reader's taste. For each one you select, cite the specific "
        "fact and/or memory ids (from the lists above) that support "
        "recommending it — cite only ids that appear above, and only ones "
        "that genuinely support the selection. You have NO information about "
        "what any candidate book is actually about — its plot, genre, "
        "themes, or content are all unknown to you. Do not state or imply "
        "anything about a candidate's content. Your only job is to say "
        "which of the reader's own facts/memories make each candidate worth "
        "recommending.",
        "",
        'Return ONLY a JSON object with one key, "recommendations", a list of '
        'objects each with "media_item_id" (one of the candidate ids above) '
        'and "cites" (a list of objects with "type", either "preference_fact" '
        'or "memory", and "id"). No preamble, no explanation, no markdown '
        "fencing.",
    ]
    return "\n".join(lines)
