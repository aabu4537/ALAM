"""The ``preference_fact_evidence`` join table — the pointers from an L3 fact
back to the L2 memories that produced it (ADR-0001).

A plain link row, not an entity with its own lifecycle: no surrogate id, no
``updated_at`` (a link is never edited, only created or removed with its
memory). ``ON DELETE CASCADE`` from ``memories`` means a deleted memory's
evidence link disappears with it.

**Known gap, same shape as the one M2 documented for structure units**: if
deleting a memory empties out a fact's last piece of evidence, that fact is
not automatically removed or flagged — ADR-0001 calls this out as something
deletion cascading must eventually handle, but no memory-deletion path exists
yet anywhere in the codebase to trigger it. Real limitation, not silently
swallowed; revisit when deletion is actually built.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, PrimaryKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base


class PreferenceFactEvidence(Base):
    __tablename__ = "preference_fact_evidence"

    preference_fact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("preference_facts.id", ondelete="CASCADE"), nullable=False
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        PrimaryKeyConstraint("preference_fact_id", "memory_id", name="pk_preference_fact_evidence"),
    )

    def __repr__(self) -> str:
        return (
            f"<PreferenceFactEvidence preference_fact_id={self.preference_fact_id} "
            f"memory_id={self.memory_id}>"
        )
