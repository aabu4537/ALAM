"""Structured extraction prompt (M2 session 3): decompose a corrected
transcript into typed memories per ADR-0001's fixed enum.

Requests JSON as plain text rather than widening ``LLMProvider`` with a "JSON
mode" — its own docstring frames structured output as a future widening for a
caller that doesn't exist yet, and asking for JSON in the prompt and
parsing/validating it in ``ai/extraction/`` (a pure function) gets the same
result without touching the provider interface.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

PROMPT_VERSION_ID = "extract-memories-v1"

_MEMORY_TYPES = (
    "prediction",
    "opinion",
    "emotional_reaction",
    "confusion",
    "character_judgment",
    "favorite_moment",
    "meta_comment",
    "other",
)


def build_extraction_prompt(transcript: str) -> str:
    types = ", ".join(_MEMORY_TYPES)
    lines = [
        "You are decomposing a reader's spoken reflection on a book into "
        "discrete memories. Read the transcript and identify every distinct "
        "thought it contains: a prediction, an opinion, an emotional "
        "reaction, a confusion, a judgment of a character, a favorite "
        "moment, or a meta-comment about the book itself. One transcript "
        "often contains several.",
        "",
        f"Each memory must have a memory_type from exactly this set: {types}. "
        'Use "other" only when nothing else fits.',
        "",
        "For each memory, write its content as a short, self-contained "
        "canonical statement, not a quote: a clean paraphrase capturing "
        "just that one thought (e.g. 'The narrator is concealing his "
        "brother's death' rather than the reader's rambling words).",
        "",
        "Return ONLY a JSON array of objects, each with memory_type and "
        "content keys. No preamble, no explanation, no markdown fencing. "
        "If the transcript contains no clear memory, return [].",
        "",
        f"Transcript:\n{transcript}",
    ]
    return "\n".join(lines)
