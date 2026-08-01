"""Prediction listing for display (M5 session 3): joins a book's predictions
back to their source and evidence memories' text, the same shape
``services/taste_drift.py`` builds for preference facts.

Reuses ``PredictionResolutionError`` for a prediction (or its evidence) whose
memory is missing — the same "shouldn't happen given ``ON DELETE CASCADE``"
invariant ``services/prediction_resolution.py`` guards, just observed from a
read path instead of the resolution job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.predictions import PredictionRepository
from alam.services.prediction_resolution import PredictionResolutionError

if TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models.prediction import PredictionStatus


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
    session: Session, *, media_item_id: uuid.UUID
) -> list[PredictionView]:
    predictions = PredictionRepository(session)
    memories = MemoryRepository(session)

    views = []
    for prediction in predictions.list_for_media_item(media_item_id):
        source = memories.get(prediction.source_memory_id)
        if source is None:
            raise PredictionResolutionError(
                f"prediction {prediction.id} has no source memory {prediction.source_memory_id}"
            )

        evidence = []
        for memory_id in predictions.list_evidence_memory_ids(prediction.id):
            evidence_memory = memories.get(memory_id)
            if evidence_memory is None:
                raise PredictionResolutionError(
                    f"prediction {prediction.id} has no evidence memory {memory_id}"
                )
            evidence.append(evidence_memory.content)

        views.append(
            PredictionView(
                id=prediction.id,
                statement=source.content,
                status=prediction.status,
                made_at_ordinal=prediction.made_at_ordinal,
                resolution_window=prediction.resolution_window,
                resolved_at=prediction.resolved_at,
                evidence=evidence,
            )
        )
    return views
