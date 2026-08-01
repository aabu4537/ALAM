"""Recommendations prompt (M6 session 2, widened M6 session 3, ADR-0015):
pick the reader's own to-read shelf candidates worth surfacing, backed by
their own preference facts and memories — and, for a candidate
``CatalogProvider`` has already fetched, its own catalog blurb/subjects.

Instructs the model to select, not describe — cite specific fact/memory/
catalog ids for each candidate rather than writing anything new. This
instruction is not what makes an unsourced characterization impossible,
though: the response schema (``ai/synthesis/recommendations.py``) has no
field for one to occupy regardless of what the model attempts, the same
caveat ADR-0013 already states for Layer 2 ("nothing stops a model from
ignoring the instruction") applied to why the real enforcement lives in the
schema, not here.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "recommendations-v2"

MAX_RECOMMENDATIONS = 5
"""Requested in the prompt text, not enforced by the schema — the model may
return fewer if fewer candidates genuinely match."""


@dataclass(frozen=True)
class CandidateBook:
    media_item_id: str
    title: str
    author: str | None
    blurb: str | None = None
    subjects: Sequence[str] = ()
    """Set only when ``CatalogProvider`` has already fetched this
    candidate's ``attributes["catalog"]`` (M6 session 3) — most candidates
    won't have this until the backfill reaches them, and that's fine: a
    candidate with no catalog data is still recommendable on taste alone,
    same as every candidate was in session 2."""


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
    """``candidates`` are the reader's own to-read shelf. ``facts``/
    ``memories`` are the reader's own recorded taste evidence, each tagged
    with its id for citation. A candidate with ``blurb``/``subjects`` set
    may be cited with ``type="catalog"``; one without still may not have
    anything about its content stated or implied."""
    candidates_block = "\n".join(_candidate_lines(c) for c in candidates) or "(none)"
    facts_block = "\n".join(f"- id={f.id}: {f.statement}" for f in facts) or "(none recorded yet)"
    memories_block = (
        "\n".join(f"- id={m.id}: {m.content}" for m in memories) or "(none recorded yet)"
    )

    lines = [
        "A reader has these books on their to-read shelf, each with an id. "
        'Some have a "Known:" line — a real, catalog-sourced description — '
        "and some don't:",
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
        "fact/memory ids (from the lists above) that support recommending "
        'it, and — only for a candidate with a "Known:" line — you may also '
        'cite type="catalog" with id equal to that candidate\'s own id, but '
        'only to reference what its "Known:" line actually says. For any '
        'candidate with no "Known:" line, you have NO information about '
        "what it's actually about — its plot, genre, themes, or content "
        "beyond title and author are unknown to you. Do not state or imply "
        "anything about such a candidate's content. Cite only ids that "
        "appear above, and only ones that genuinely support the selection.",
        "",
        'Return ONLY a JSON object with one key, "recommendations", a list of '
        'objects each with "media_item_id" (one of the candidate ids above) '
        'and "cites" (a list of objects with "type", one of "preference_fact", '
        '"memory", or "catalog", and "id"). No preamble, no explanation, no '
        "markdown fencing.",
    ]
    return "\n".join(lines)


def _candidate_lines(candidate: CandidateBook) -> str:
    header = f'- id={candidate.media_item_id}: "{candidate.title}"'
    if candidate.author:
        header += f" by {candidate.author}"
    if not candidate.blurb and not candidate.subjects:
        return header

    known_parts = []
    if candidate.blurb:
        known_parts.append(candidate.blurb)
    if candidate.subjects:
        known_parts.append(f"Subjects: {', '.join(candidate.subjects)}.")
    return header + f"\n  Known: {' '.join(known_parts)}"
