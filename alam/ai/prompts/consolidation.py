"""Consolidation prompt (M4 session 2): decide what a batch of new episodic
memories does to a reader's existing preference profile.

Same reasoning as ``ai/prompts/extraction.py`` for requesting plain-JSON
output rather than widening ``LLMProvider``: parsing and validation live in
``ai/consolidation/actions.py``, a pure function, not in the provider
interface.

Versioned per CLAUDE.md rule 6. Bump ``PROMPT_VERSION_ID`` on any wording
change; do not edit the template text and keep the old id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

PROMPT_VERSION_ID = "consolidate-preferences-v1"


def build_consolidation_prompt(
    *,
    existing_facts: Sequence[tuple[str, str]],
    new_memories: Sequence[tuple[str, str]],
) -> str:
    """``existing_facts`` and ``new_memories`` are each ``(id, text)`` pairs —
    the reader's current active preference facts, and the batch of new
    episodic memories to weigh against them."""
    facts_block = (
        "\n".join(f"- {fact_id}: {statement}" for fact_id, statement in existing_facts)
        if existing_facts
        else "(none yet — this reader has no preference facts recorded)"
    )
    memories_block = "\n".join(f"- {memory_id}: {content}" for memory_id, content in new_memories)

    lines = [
        "You maintain a reader's preference profile from their reflections on "
        "books. Below is their current set of active preference facts, and a "
        "batch of new memories extracted from reflections they haven't been "
        "weighed against yet. Decide what each new memory means for the "
        "profile.",
        "",
        "Existing active preference facts (id: statement):",
        facts_block,
        "",
        "New memories to weigh (id: content):",
        memories_block,
        "",
        "For each preference pattern you find in the new memories, choose exactly one action:",
        '- "new": a preference not already covered by any existing fact. '
        'Write a short, general statement (e.g. "prefers unreliable '
        'narrators"), not a restatement of one memory.',
        '- "reinforce": a new memory confirms an existing fact. Cite the existing fact\'s id.',
        '- "supersede": a new memory contradicts an existing fact (the '
        "reader's taste has shifted). Cite the old fact's id and write the "
        "new statement that replaces it.",
        "",
        "Not every memory reveals a preference — predictions, confusions, and "
        "one-off reactions often don't. Leave those out; do not force an "
        "action onto a memory that doesn't support one. Every action must "
        "cite at least one new memory id as evidence.",
        "",
        "Return ONLY a JSON array of objects, each with an action key "
        '("new", "reinforce", or "supersede"), a memory_ids key (array of '
        "the new memory ids supporting it), and — depending on the action — "
        "a statement key (new/supersede) and/or a fact_id key "
        "(reinforce/supersede). No preamble, no explanation, no markdown "
        "fencing. If nothing in this batch reveals a preference, return [].",
    ]
    return "\n".join(lines)
