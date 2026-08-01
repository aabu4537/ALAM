"""Journey summary prompt (M6 session 1): a short narrative of the reader's
progress through one book so far, grounded only in their own recorded
reflections and predictions.

States the reader's current position explicitly (ADR-0002 Layer 2 — this is
its first real caller) and instructs the model not to draw on anything past
that position or on outside knowledge of the book. Layer 2 alone is not a
guarantee — the model has the book in its weights regardless of what the
prompt says — which is exactly why Layer 3 (``ai/synthesis/leak_check.py``)
checks the draft this prompt produces rather than trusting the instruction.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "journey-summary-v1"


def build_journey_summary_prompt(
    *,
    book_title: str,
    current_ordinal: int,
    memories: Sequence[str],
    predictions: Sequence[str],
) -> str:
    """``memories`` and ``predictions`` are the reader's own words — already
    ordinal-filtered by the caller — never the book's text. Both oldest
    first."""
    memories_block = "\n".join(f"- {content}" for content in memories) or "(none recorded yet)"
    predictions_block = "\n".join(f"- {content}" for content in predictions) or "(none made yet)"

    lines = [
        f'A reader is partway through the book "{book_title}", currently at '
        f"position {current_ordinal} in its structure.",
        "",
        "Here is everything they have recorded about their reading journey so "
        "far, in their own words, oldest first:",
        "",
        "Reflections:",
        memories_block,
        "",
        "Predictions they made:",
        predictions_block,
        "",
        "Write a short narrative summary (2-4 sentences) of their reading "
        "journey through this book so far — what they've reacted to, "
        "wondered about, and predicted. Use ONLY the reflections and "
        "predictions above. Do not use any other knowledge you may have of "
        "this book, and do not mention or allude to anything that might "
        "happen after the reader's current position — you have not been "
        "told what happens next, and must not guess.",
        "",
        'Return ONLY a JSON object with one key, "narrative", whose value is '
        "the summary text. No preamble, no explanation, no markdown fencing.",
    ]
    return "\n".join(lines)
