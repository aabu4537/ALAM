"""Prediction listing for display (M5 session 3; ordinal-scoped per ADR-0012),
joining a book's predictions back to their source and evidence memories'
text, the same shape ``services/taste_drift.py`` builds for preference facts.

Reuses ``PredictionResolutionError`` for a prediction (or its evidence) whose
memory is missing — the same "shouldn't happen given ``ON DELETE CASCADE``"
invariant ``services/prediction_resolution.py`` guards, just observed from a
read path instead of the resolution job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.domain.spoiler_filter import is_visible, visible_prediction_status
from alam.persistence.models.prediction import PredictionStatus
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.predictions import PredictionRepository
from alam.services.prediction_resolution import PredictionResolutionError

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.orm import Session

    from alam.domain.reader_context import ReaderContext


@dataclass(frozen=True)
class PredictionView:
    id: uuid.UUID
    statement: str
    status: PredictionStatus
    made_at_ordinal: int
    resolution_window: int
    resolved_at: dt.datetime | None
    evidence: list[str]


def list_predictions_for_book(
    session: Session, *, reader_context: ReaderContext
) -> list[PredictionView]:
    """Ordinal-scoped by ``reader_context.current_ordinal``, not by which
    reading session made or resolved a prediction (ADR-0012) — a prediction
    made past the reader's current position is omitted entirely, and one
    made at or before it but not yet due for resolution
    (``domain.spoiler_filter.visible_prediction_status``) renders ``pending``
    with no evidence even if it was already resolved during an earlier,
    further-along session.
    """
    predictions = PredictionRepository(session)
    memories = MemoryRepository(session)
    current_ordinal = reader_context.current_ordinal

    views = []
    for prediction in predictions.list_for_media_item(reader_context.media_item_id):
        if not is_visible(
            structure_ordinal=prediction.made_at_ordinal, current_ordinal=current_ordinal
        ):
            continue

        source = memories.get(prediction.source_memory_id)
        if source is None:
            raise PredictionResolutionError(
                f"prediction {prediction.id} has no source memory {prediction.source_memory_id}"
            )

        display_status = PredictionStatus(
            visible_prediction_status(
                status=prediction.status.value,
                made_at_ordinal=prediction.made_at_ordinal,
                resolution_window=prediction.resolution_window,
                current_ordinal=current_ordinal,
            )
        )

        evidence: list[str] = []
        resolved_at = None
        if display_status is not PredictionStatus.PENDING:
            resolved_at = prediction.resolved_at
            for memory_id in predictions.list_evidence_memory_ids(prediction.id):
                evidence_memory = memories.get(memory_id)
                if evidence_memory is None:
                    raise PredictionResolutionError(
                        f"prediction {prediction.id} has no evidence memory {memory_id}"
                    )
                # Defense-in-depth, same rationale as hybrid retrieval
                # re-checking `filter_visible` after fusion: due status
                # already implies every evidence ordinal is in range, but
                # re-checking here means the two can never quietly drift.
                if is_visible(
                    structure_ordinal=evidence_memory.structure_ordinal,
                    current_ordinal=current_ordinal,
                ):
                    evidence.append(evidence_memory.content)

        views.append(
            PredictionView(
                id=prediction.id,
                statement=source.content,
                status=display_status,
                made_at_ordinal=prediction.made_at_ordinal,
                resolution_window=prediction.resolution_window,
                resolved_at=resolved_at,
                evidence=evidence,
            )
        )
    return views
