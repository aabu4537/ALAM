from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.persistence.models.prediction import Prediction, PredictionStatus
from alam.persistence.models.prediction_evidence import PredictionEvidence

if TYPE_CHECKING:
    import datetime as dt
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class PredictionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        source_memory_id: uuid.UUID,
        media_item_id: uuid.UUID,
        made_at_ordinal: int,
        resolution_window: int,
    ) -> Prediction:
        prediction = Prediction(
            source_memory_id=source_memory_id,
            media_item_id=media_item_id,
            made_at_ordinal=made_at_ordinal,
            resolution_window=resolution_window,
            status=PredictionStatus.PENDING,
        )
        self._session.add(prediction)
        self._session.flush()
        return prediction

    def get(self, prediction_id: uuid.UUID) -> Prediction | None:
        return self._session.get(Prediction, prediction_id)

    def list_pending_for_media_item(self, media_item_id: uuid.UUID) -> Sequence[Prediction]:
        """Every open prediction for a book, regardless of whether its window
        has closed yet — the resolution service filters to the ones actually
        due (``domain.prediction_resolution.is_due_for_resolution``)."""
        return self._session.scalars(
            select(Prediction).where(
                Prediction.media_item_id == media_item_id,
                Prediction.status == PredictionStatus.PENDING,
            )
        ).all()

    def list_for_media_item(self, media_item_id: uuid.UUID) -> Sequence[Prediction]:
        return self._session.scalars(
            select(Prediction)
            .where(Prediction.media_item_id == media_item_id)
            .order_by(Prediction.made_at_ordinal, Prediction.created_at)
        ).all()

    def resolve(
        self,
        prediction: Prediction,
        *,
        status: PredictionStatus,
        resolved_at: dt.datetime,
        resolution_prompt_version_id: str | None,
        evidence_memory_ids: Sequence[uuid.UUID],
    ) -> Prediction:
        """Moves a pending prediction to a terminal status. Never called with
        ``status=PENDING`` — that would just be re-creating the row's default,
        and nothing here supports resolving twice (the caller only fetches
        ``PENDING`` predictions in the first place)."""
        prediction.status = status
        prediction.resolved_at = resolved_at
        prediction.resolution_prompt_version_id = resolution_prompt_version_id
        self._session.flush()
        if evidence_memory_ids:
            self._link_evidence(prediction.id, evidence_memory_ids)
        return prediction

    def list_evidence_memory_ids(self, prediction_id: uuid.UUID) -> Sequence[uuid.UUID]:
        return self._session.scalars(
            select(PredictionEvidence.memory_id).where(
                PredictionEvidence.prediction_id == prediction_id
            )
        ).all()

    def _link_evidence(self, prediction_id: uuid.UUID, memory_ids: Sequence[uuid.UUID]) -> None:
        for memory_id in memory_ids:
            self._session.add(PredictionEvidence(prediction_id=prediction_id, memory_id=memory_id))
        self._session.flush()
