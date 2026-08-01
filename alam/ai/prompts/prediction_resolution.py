"""Prediction resolution prompt (M5 session 2): decide whether a reader's
prediction was confirmed, refuted, or unresolvable, given only the memories
recorded in its evidence window (ADR-0009 — memories, not book text).

Same reasoning as ``ai/prompts/consolidation.py`` for requesting plain-JSON
output rather than widening ``LLMProvider``.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "resolve-prediction-v1"


def build_resolution_prompt(*, prediction_statement: str, evidence: Sequence[str]) -> str:
    """``evidence`` is the reader's own memory contents from the prediction's
    resolution window, oldest first — not the book's text."""
    evidence_block = "\n".join(f"- {content}" for content in evidence)

    lines = [
        "A reader made the following prediction while reading a book:",
        "",
        f'"{prediction_statement}"',
        "",
        "Since then, they recorded these reflections (their own words, not "
        "the book's text) as they kept reading:",
        "",
        evidence_block,
        "",
        "Decide the outcome of the prediction based only on what these "
        'reflections reveal: "confirmed" if they show the prediction came '
        'true, "refuted" if they show it did not, or "unresolvable" if the '
        "reflections don't clearly settle it either way — vague predictions "
        "and reflections that don't touch on the prediction at all are "
        "common; do not force a side onto a case that doesn't support one.",
        "",
        'Return ONLY a JSON object with one key, "outcome", whose value is '
        '"confirmed", "refuted", or "unresolvable". No preamble, no '
        "explanation, no markdown fencing.",
    ]
    return "\n".join(lines)
