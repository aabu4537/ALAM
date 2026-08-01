"""Journey summary generation and retrieval (M6 session 1, ADR-0013).

The first synchronous, in-request generation path M6 introduces — an
on-demand read ("summarize my journey"), not background maintenance like
consolidation or prediction resolution, so it runs inline rather than
through the job queue.

Row lifecycle, all inside one request: a ``pending`` row is written and
*committed* before any LLM call — not just flushed, same idiom
``jobs/runner.py`` uses for claiming a job before running its handler — so
a crash or an error response later in the same request cannot roll the
write back with it. Whatever happens next (a parse failure, a Layer 3
block, an unhandled exception) rolls back only that attempt's uncommitted
work and commits the row's terminal status on its own, independent of
whether the route ultimately returns 200 or raises. Without this, the
FastAPI request-level ``session_scope`` dependency rolling back on any
propagated exception would take the ``pending``/``failed``/
``blocked_leaked`` write down with it, silently defeating the whole point
of persisting a retryable row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alam.ai.prompts.journey_summary import PROMPT_VERSION_ID as JOURNEY_SUMMARY_PROMPT_VERSION_ID
from alam.ai.prompts.journey_summary import build_journey_summary_prompt
from alam.ai.prompts.leak_check import PROMPT_VERSION_ID as LEAK_CHECK_PROMPT_VERSION_ID
from alam.ai.prompts.leak_check import build_leak_check_prompt
from alam.ai.providers import get_llm_provider
from alam.ai.synthesis.journey_summary import (
    JOURNEY_SUMMARY_RESPONSE_SCHEMA,
    parse_journey_summary_response,
)
from alam.ai.synthesis.leak_check import (
    LEAK_CHECK_RESPONSE_SCHEMA,
    parse_leak_check_response,
)
from alam.domain.spoiler_filter import is_visible
from alam.domain.synthesis_staleness import is_artifact_stale
from alam.persistence.models.journey_summary import JourneySummary, JourneySummaryStatus
from alam.persistence.repositories.journey_summaries import JourneySummaryRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.services.predictions import list_predictions_for_book

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.domain.reader_context import ReaderContext
    from alam.persistence.models.memory import Memory

ORDINAL_THRESHOLD = 5
"""Ordinals of progress that must pass before a cached journey summary is
considered stale (``domain.synthesis_staleness.is_artifact_stale``). A
per-artifact-type constant, not a setting (M6 plan) — tuned per artifact
type when each is built, not speculatively now."""


class UnknownMediaItemError(LookupError):
    """The book a journey summary was requested for doesn't exist. Shouldn't
    happen given ``reader_context_dependency`` already resolved it, kept
    explicit rather than trusted implicitly."""


class JourneySummaryBlockedError(RuntimeError):
    """A freshly generated journey summary failed the Layer 3 leak check.
    The row is persisted ``blocked_leaked`` for audit; its draft must never
    reach a caller. The router turns this into an error response, never the
    leaked draft and never a silent fallback to a stale cached row."""


class JourneySummaryGenerationError(RuntimeError):
    """Generation failed for a reason other than a Layer 3 block — a
    response that didn't parse, most likely. The row is persisted
    ``failed`` with the error recorded, so a retry has something to find."""


def get_or_generate_journey_summary(
    session: Session, *, reader_context: ReaderContext
) -> JourneySummary:
    """Returns the latest ``complete`` artifact if one exists and is not
    stale; otherwise generates fresh, persists the result, and returns it."""
    journey_summaries = JourneySummaryRepository(session)
    existing = journey_summaries.get_latest_for_media_item(reader_context.media_item_id)

    if existing is not None and existing.status is JourneySummaryStatus.COMPLETE:
        stale = is_artifact_stale(
            generated_at_ordinal=existing.generated_at_ordinal,
            current_ordinal=reader_context.current_ordinal,
            ordinal_threshold=ORDINAL_THRESHOLD,
            artifact_prompt_version_id=existing.prompt_version_id or "",
            current_prompt_version_id=JOURNEY_SUMMARY_PROMPT_VERSION_ID,
        )
        if not stale:
            return existing

    return _generate(session, reader_context=reader_context)


def _generate(session: Session, *, reader_context: ReaderContext) -> JourneySummary:
    media_item = MediaItemRepository(session).get(reader_context.media_item_id)
    if media_item is None:
        raise UnknownMediaItemError(f"no media item {reader_context.media_item_id}")

    journey_summaries = JourneySummaryRepository(session)
    row = journey_summaries.create_pending(
        media_item_id=reader_context.media_item_id,
        generated_at_ordinal=reader_context.current_ordinal,
    )
    session.commit()  # durable before the LLM call — see the module docstring

    current_ordinal = reader_context.current_ordinal
    all_memories = MemoryRepository(session).list_for_media_item(reader_context.media_item_id)
    visible_memories = [
        m
        for m in all_memories
        if is_visible(structure_ordinal=m.structure_ordinal, current_ordinal=current_ordinal)
    ]
    excluded_memories = [
        m
        for m in all_memories
        if not is_visible(structure_ordinal=m.structure_ordinal, current_ordinal=current_ordinal)
    ]
    predictions = list_predictions_for_book(session, reader_context=reader_context)
    excluded_snapshot = _excluded_snapshot(excluded_memories)

    try:
        summary_prompt = build_journey_summary_prompt(
            book_title=media_item.title,
            current_ordinal=current_ordinal,
            memories=[m.content for m in visible_memories],
            predictions=[f"{p.statement} (status: {p.status.value})" for p in predictions],
        )
        summary_completion = get_llm_provider().complete(
            summary_prompt,
            prompt_version_id=JOURNEY_SUMMARY_PROMPT_VERSION_ID,
            response_schema=JOURNEY_SUMMARY_RESPONSE_SCHEMA,
        )
        draft = parse_journey_summary_response(summary_completion.text)

        leak_prompt = build_leak_check_prompt(
            draft=draft.narrative, excluded_content=[m.content for m in excluded_memories]
        )
        leak_completion = get_llm_provider().complete(
            leak_prompt,
            prompt_version_id=LEAK_CHECK_PROMPT_VERSION_ID,
            response_schema=LEAK_CHECK_RESPONSE_SCHEMA,
        )
        leak_result = parse_leak_check_response(leak_completion.text)
    except Exception as exc:
        # Any failure between the pending row and a terminal status — a
        # response that didn't parse, a provider error — leaves a `failed`
        # row with the reason recorded, rather than one stuck `pending`
        # forever with the LLM call already spent. Rollback first, same
        # idiom `jobs/runner.py` uses on a handler failure: discard whatever
        # this attempt left uncommitted before writing the failure against a
        # clean transaction.
        session.rollback()
        journey_summaries.mark_failed(row, error=str(exc))
        session.commit()
        raise JourneySummaryGenerationError(str(exc)) from exc

    if leak_result.leaked:
        journey_summaries.mark_blocked_leaked(
            row,
            draft=draft.narrative,
            model=summary_completion.model,
            prompt_version_id=JOURNEY_SUMMARY_PROMPT_VERSION_ID,
            layer3_spans=leak_result.spans,
            excluded_snapshot=excluded_snapshot,
        )
        session.commit()
        raise JourneySummaryBlockedError(
            f"journey summary for media item {reader_context.media_item_id} "
            "was blocked by the Layer 3 leak check"
        )

    result = journey_summaries.mark_complete(
        row,
        draft=draft.narrative,
        model=summary_completion.model,
        prompt_version_id=JOURNEY_SUMMARY_PROMPT_VERSION_ID,
        excluded_snapshot=excluded_snapshot,
    )
    session.commit()
    return result


def _excluded_snapshot(excluded_memories: list[Memory]) -> list[dict[str, Any]]:
    return [
        {
            "memory_id": str(m.id),
            "structure_ordinal": m.structure_ordinal,
            "content": m.content,
        }
        for m in excluded_memories
    ]
