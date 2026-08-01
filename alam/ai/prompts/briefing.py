"""Briefing prompt (M6 session 4): select which of the reader's own facts
and memories — about books other than the candidate — plausibly connect to
a book they're about to start.

The candidate's ``subjects`` (never its ``blurb`` text — subjects are
enough for relevance-matching, and keeping the blurb out of the prompt
removes any reason for the model to echo or paraphrase it) are informational
context for the *selection* task only. Instructs the model to select, not
describe — same "cite, don't write" framing
``ai/prompts/recommendations.py`` uses, backed the same way: the response
schema (``ai/synthesis/briefing.py``) has no field for a sentence about the
candidate's own content to occupy, so the instruction is reinforcement, not
the actual guarantee.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from alam.ai.prompts.recommendations import FactForPrompt, MemoryForPrompt

PROMPT_VERSION_ID = "briefing-v1"

MAX_CITATIONS = 3
"""Requested in the prompt text, not enforced by the schema — the model may
return fewer, including none, if nothing genuinely connects."""


def build_briefing_prompt(
    *,
    book_title: str,
    book_author: str | None,
    subjects: Sequence[str],
    facts: Sequence[FactForPrompt],
    memories: Sequence[MemoryForPrompt],
) -> str:
    """``facts``/``memories`` are the reader's own recorded taste evidence
    from *other* books, each tagged with its id for citation. ``subjects``
    is the candidate's own catalog-sourced subject list, if fetched — may
    be empty."""
    header = f'A reader is about to start "{book_title}"'
    if book_author:
        header += f" by {book_author}"
    header += "."
    subjects_block = (
        f"Its catalog listing gives these subjects: {', '.join(subjects)}."
        if subjects
        else "No catalog subjects are known for it."
    )
    facts_block = "\n".join(f"- id={f.id}: {f.statement}" for f in facts) or "(none recorded yet)"
    memories_block = (
        "\n".join(f"- id={m.id}: {m.content}" for m in memories) or "(none recorded yet)"
    )

    lines = [
        header,
        subjects_block,
        "",
        "Here is everything known about the reader's taste from books they "
        "have read before, each entry tagged with its id:",
        "",
        "Preference facts (consolidated observations about their taste):",
        facts_block,
        "",
        "Memories (their own recorded reflections while reading other books):",
        memories_block,
        "",
        f"Select up to {MAX_CITATIONS} of the facts/memories above that "
        "plausibly connect to this candidate's subjects. Cite only ids that "
        "appear above, and only ones that genuinely support the connection. "
        "You have NOT been given this candidate's plot, characters, or "
        "events — nothing about its content beyond the subjects above is "
        "known to you. Do not state or imply anything about what happens in "
        "it; select citations only, no explanation text.",
        "",
        'Return ONLY a JSON object with one key, "cites", a list of objects '
        'each with "type" (one of "preference_fact" or "memory") and "id". '
        "Return an empty list if nothing genuinely connects. No preamble, no "
        "explanation, no markdown fencing.",
    ]
    return "\n".join(lines)
