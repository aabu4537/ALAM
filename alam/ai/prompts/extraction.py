"""Structured extraction prompt (M2 session 3, rewritten M5.5a follow-up
task 2): decompose a corrected transcript into typed memories per
ADR-0001's fixed enum.

Requests JSON in the prompt text (as before) *and*, where the provider
supports it, is paired with ``ai/extraction/memories.py``'s
``EXTRACTION_RESPONSE_SCHEMA`` via ``LLMProvider.complete()``'s
``response_schema`` parameter — schema-constrained decoding fixes the wire
*shape* (array vs. object), but does nothing about which categories a weak
model chooses to fill in, which is a prompt problem, not a schema one. See
below.

**v2 wording change, not cosmetic:** v1 listed the eight memory types as
"identify every distinct thought it contains: a prediction, an opinion,
...", immediately followed by "one transcript often contains several." A
1B-parameter local model (`llama3.2:1b`) read that as a template to fill in
one value per category, not a set to choose from — every one of 8 baseline
extraction cases came back with content for all 7-8 types, including
fabricated content for types that didn't apply, rather than the 1-2 that
did (see ``docs/eval/baseline-local-providers.md``'s follow-up diagnosis).
v2 is explicit in the opposite direction: state outright that most
transcripts yield one or two memories, and that a type not present must be
left out of the array entirely, not filled with a placeholder.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

PROMPT_VERSION_ID = "extract-memories-v2"

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
        "discrete memories. A memory_type is a category a thought can belong "
        "to, not a slot you must fill. Most transcripts contain only one or "
        "two distinct thoughts — do not invent content for a type just "
        "because it's in the list below.",
        "",
        f"The available categories are: {types}. For each thought the "
        "transcript actually contains, pick the one category that fits best. "
        'Use "other" only when nothing else fits.',
        "",
        "If a category is not represented in the transcript, it must not "
        "appear in your output at all — never include a placeholder value "
        'like "None" or an empty string for a type that isn\'t there. A '
        "transcript expressing only one opinion produces exactly one memory, "
        "not eight.",
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
