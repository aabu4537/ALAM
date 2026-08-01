"""The ``prediction_evidence`` join table — pointers from a resolved
prediction back to the memories in its resolution window that were weighed
to reach an outcome (M5). Same shape as ``preference_fact_evidence``: a
plain link row, no surrogate id, no ``updated_at``, ``ON DELETE CASCADE``
from both sides.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, PrimaryKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base


class PredictionEvidence(Base):
    __tablename__ = "prediction_evidence"

    prediction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("prediction_id", "memory_id", name="pk_prediction_evidence"),
    )

    def __repr__(self) -> str:
        return f"<PredictionEvidence prediction_id={self.prediction_id} memory_id={self.memory_id}>"
