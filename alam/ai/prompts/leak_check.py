"""Layer 3 leak-check prompt (M6, ADR-0002, ADR-0013).

A narrow question, not "is this a spoiler in general" (ADR-0002's own framing
of why Layer 3 is tractable): does the draft leak anything from the specific
set of content the ordinal filter excluded from it. Shared by every M6
synthesis artifact type.

Versioned per CLAUDE.md rule 6, independent of whichever artifact's prompt
produced the draft being checked — this is a separate LLM call with its own
provenance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "leak-check-v1"


def build_leak_check_prompt(*, draft: str, excluded_content: Sequence[str]) -> str:
    """``excluded_content`` is the reader's own memory/prediction text that
    was retrieved but excluded by the ordinal filter — content from further
    ahead in the book than the reader has reached. Not the book's raw text."""
    excluded_block = "\n".join(f"- {content}" for content in excluded_content) or "(none)"

    lines = [
        "Below is a draft of AI-generated text shown to a reader who is "
        "partway through a book, and a list of statements describing things "
        "that happen LATER in the book than the reader has currently read — "
        "the reader must not learn any of this yet.",
        "",
        "Excluded content (must not appear or be inferable in the draft):",
        excluded_block,
        "",
        "Draft:",
        f'"{draft}"',
        "",
        "Does the draft reveal, state, or strongly imply any of the excluded "
        "content — whether by quoting it, paraphrasing it, or letting a "
        "reader infer it? Judge meaning, not just exact wording.",
        "",
        'Return ONLY a JSON object with two keys: "leaked" (boolean), and '
        '"spans" (a JSON array of verbatim substrings copied exactly from '
        "the draft that leak excluded content — empty array if leaked is "
        "false). No preamble, no explanation, no markdown fencing.",
    ]
    return "\n".join(lines)
