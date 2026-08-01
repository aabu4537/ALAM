"""Prediction resolution (M5 session 2, ADR-0009): checks every pending
prediction for one book against the reader's current progress, and resolves
the ones whose window has closed.

Triggered whenever a capture advances a reading session's ``current_ordinal``
(``services/capture_submission.py``) rather than on a periodic schedule —
"progress crosses `made_at_ordinal + N`" (docs/milestones.md, M5) happens
exactly at that moment, so there is nothing to gain from also polling.

A prediction with no evidence memories in its window resolves
``unresolvable`` without an LLM call — there's nothing to weigh it against,
so a call would only spend money to confirm a foregone conclusion.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from alam.ai.prediction_resolution.outcome import ResolutionOutcome, parse_resolution_response
from alam.ai.prompts.prediction_resolution import PROMPT_VERSION_ID, build_resolution_prompt
from alam.ai.providers import get_llm_provider
from alam.domain.prediction_resolution import evidence_window, is_due_for_resolution
from alam.persistence.models.prediction import PredictionStatus
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.predictions import PredictionRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_OUTCOME_TO_STATUS = {
    ResolutionOutcome.CONFIRMED: PredictionStatus.CONFIRMED,
    ResolutionOutcome.REFUTED: PredictionStatus.REFUTED,
    ResolutionOutcome.UNRESOLVABLE: PredictionStatus.UNRESOLVABLE,
}


class PredictionResolutionError(LookupError):
    """A due prediction's source memory is missing — shouldn't happen given
    the ``ON DELETE CASCADE`` from memory to prediction, but resolving
    against a statement that no longer exists would be worse than failing
    the job loudly."""


def resolve_due_predictions(session: Session, payload: dict[str, Any]) -> None:
    media_item_id = uuid.UUID(payload["media_item_id"])

    reading_session = ReadingSessionRepository(session).get_active_for_media_item(media_item_id)
    if reading_session is None:
        return  # nothing has advanced progress for this book yet

    predictions = PredictionRepository(session)
    memories = MemoryRepository(session)
    now = dt.datetime.now(dt.UTC)

    for prediction in predictions.list_pending_for_media_item(media_item_id):
        if not is_due_for_resolution(
            made_at_ordinal=prediction.made_at_ordinal,
            resolution_window=prediction.resolution_window,
            current_ordinal=reading_session.current_ordinal,
        ):
            continue

        from_ordinal, to_ordinal = evidence_window(
            made_at_ordinal=prediction.made_at_ordinal,
            resolution_window=prediction.resolution_window,
        )
        evidence = memories.list_in_ordinal_range(
            media_item_id=media_item_id, from_ordinal=from_ordinal, to_ordinal=to_ordinal
        )

        if not evidence:
            predictions.resolve(
                prediction,
                status=PredictionStatus.UNRESOLVABLE,
                resolved_at=now,
                resolution_prompt_version_id=None,
                evidence_memory_ids=[],
            )
            continue

        source_memory = memories.get(prediction.source_memory_id)
        if source_memory is None:
            raise PredictionResolutionError(
                f"prediction {prediction.id} has no source memory {prediction.source_memory_id}"
            )

        prompt = build_resolution_prompt(
            prediction_statement=source_memory.content,
            evidence=[memory.content for memory in evidence],
        )
        completion = get_llm_provider().complete(prompt, prompt_version_id=PROMPT_VERSION_ID)
        resolution = parse_resolution_response(completion.text)

        predictions.resolve(
            prediction,
            status=_OUTCOME_TO_STATUS[resolution.outcome],
            resolved_at=now,
            resolution_prompt_version_id=PROMPT_VERSION_ID,
            evidence_memory_ids=[memory.id for memory in evidence],
        )
