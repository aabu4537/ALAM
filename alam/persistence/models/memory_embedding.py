"""``memory_embeddings`` — ADR-0008: embeddings live in a side table, not a
column on ``memories``, so a model swap is an ``INSERT`` rather than a
migration.

The vector column carries no fixed dimension: rows from different models
with different widths coexist for the same memory, distinguished by
``(memory_id, embedding_model, embedding_version)``. Every retrieval query
must scope to one model/version pair before comparing — mismatched
dimensions are never supposed to meet the ``<=>`` operator, and nothing here
enforces that at the schema level.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MemoryEmbedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_embeddings"

    memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )

    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    """sha256 hex digest of (content, embedding_model, embedding_version),
    computed before the provider is ever called (ADR-0008). Indexed, not
    unique: two different memories can share identical content (duplicate
    demo data, a repeated phrase), and both legitimately need their own row
    keyed on their own memory_id. A hit lets the backfill reuse the existing
    vector for the second one instead of paying for another provider call —
    the actual uniqueness guarantee is the natural key below. 64 chars is an
    exact hex sha256 digest, not a guess."""

    vector: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    """No fixed dimension — see the module docstring and ADR-0008."""

    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "embedding_model",
            "embedding_version",
            name="uq_memory_embeddings_memory_model_version",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryEmbedding id={self.id} memory_id={self.memory_id} "
            f"model={self.embedding_model} version={self.embedding_version}>"
        )
