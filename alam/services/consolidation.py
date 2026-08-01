"""Weekly preference consolidation (ADR-0001, M4 session 2): one bounded
batch per job invocation, chained via re-enqueue — first across a user's own
backlog, then across users — the same resumability shape
``services/embedding_backfill.py`` uses for its cursor.

Safe to be killed mid-run for the same reason: the runner commits a whole
invocation's work (every fact created/reinforced/superseded, every memory
marked consolidated, the next job's enqueue) or none of it. A killed
invocation never marked its batch consolidated, so the next claim re-derives
the identical batch from ``list_needing_consolidation``.

Triggered weekly by Supabase Cron via ``POST
/internal/preferences/consolidate`` — see ``jobs/job_types.py``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from alam.ai.consolidation.actions import ConsolidationActionType, parse_consolidation_response
from alam.ai.prompts.consolidation import PROMPT_VERSION_ID, build_consolidation_prompt
from alam.ai.providers import get_llm_provider
from alam.config.settings import get_settings
from alam.jobs.job_types import CONSOLIDATE_PREFERENCES
from alam.jobs.queue import JobQueue
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.preference_facts import PreferenceFactRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ConsolidationActionError(ValueError):
    """An action cited a fact_id that isn't in the active-facts list this
    batch's prompt actually offered — an LLM hallucination, not a bug in the
    parser (which only validates shape). Fails the job loudly rather than
    silently dropping the action."""


def consolidate_preferences(session: Session, payload: dict[str, Any]) -> None:
    settings = get_settings()
    memories = MemoryRepository(session)
    facts = PreferenceFactRepository(session)

    user_id_raw = payload.get("user_id")
    user_id = (
        uuid.UUID(user_id_raw)
        if user_id_raw
        else memories.next_user_id_needing_consolidation(after_user_id=None)
    )
    if user_id is None:
        return  # nothing anywhere needs consolidation

    batch = memories.list_needing_consolidation(
        user_id=user_id, limit=settings.consolidation_batch_size
    )
    if not batch:
        _chain_to_next_user(session, memories, after_user_id=user_id)
        return

    now = dt.datetime.now(dt.UTC)
    active_facts = facts.list_active_for_user(user_id)
    facts_by_id = {fact.id: fact for fact in active_facts}

    prompt = build_consolidation_prompt(
        existing_facts=[(str(fact.id), fact.statement) for fact in active_facts],
        new_memories=[(str(memory.id), memory.content) for memory in batch],
    )
    completion = get_llm_provider().complete(prompt, prompt_version_id=PROMPT_VERSION_ID)
    actions = parse_consolidation_response(completion.text)

    for action in actions:
        if action.action is ConsolidationActionType.NEW:
            if not action.statement:
                # Unreachable given ConsolidationAction's validator; guarded
                # explicitly rather than asserted so mypy narrows the type
                # without relying on assertions surviving in production.
                raise ConsolidationActionError("a 'new' action was missing its statement")
            facts.create(
                user_id=user_id,
                statement=action.statement,
                base_confidence=settings.consolidation_initial_confidence,
                observed_at=now,
                evidence_memory_ids=action.memory_ids,
            )
            continue

        fact = facts_by_id.get(action.fact_id) if action.fact_id is not None else None
        if fact is None:
            raise ConsolidationActionError(
                f"{action.action.value} cited fact_id {action.fact_id}, which is not "
                f"one of this batch's active facts for user {user_id}"
            )
        if action.action is ConsolidationActionType.REINFORCE:
            facts.reinforce(
                fact, reinforced_at=now, additional_evidence_memory_ids=action.memory_ids
            )
        else:  # SUPERSEDE
            if not action.statement:
                raise ConsolidationActionError("a 'supersede' action was missing its statement")
            facts.supersede(
                fact,
                statement=action.statement,
                base_confidence=settings.consolidation_initial_confidence,
                observed_at=now,
                evidence_memory_ids=action.memory_ids,
            )

    memories.mark_consolidated([memory.id for memory in batch], consolidated_at=now)

    if len(batch) == settings.consolidation_batch_size:
        # A full batch means this user may have more; stay on them.
        JobQueue(session).enqueue(
            job_type=CONSOLIDATE_PREFERENCES, payload={"user_id": str(user_id)}
        )
    else:
        _chain_to_next_user(session, memories, after_user_id=user_id)


def _chain_to_next_user(
    session: Session, memories: MemoryRepository, *, after_user_id: uuid.UUID
) -> None:
    next_user_id = memories.next_user_id_needing_consolidation(after_user_id=after_user_id)
    if next_user_id is not None:
        JobQueue(session).enqueue(
            job_type=CONSOLIDATE_PREFERENCES, payload={"user_id": str(next_user_id)}
        )
