"""Embedding provider Protocol.

Every embedding carries ``model`` and ``version`` because rule 7 requires every
table with an embedding column to store them — that is what makes a model
migration incremental rather than stop-the-world, since rows embedded with the
old model remain identifiable and can be re-embedded in batches.

``embed`` takes a sequence and returns a list. Embedding one text per call is
the standard way to make M3 slow and expensive, and a batch interface that is
called with one item costs nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Sequence


class Embedding(BaseModel):
    model_config = {"frozen": True}

    vector: list[float]

    model: str
    """Recorded on every row. Rule 7."""

    version: str
    """Distinct from ``model``: the same model name can be re-versioned by a
    provider, and a silent change would corrupt similarity comparisons between
    old and new rows without any error."""

    dimensions: int = Field(gt=0)


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def dimensions(self) -> int:
        """Fixes the pgvector column width at M3.

        Changing it later means a migration plus re-embedding everything, so
        the value is read from the provider rather than hardcoded anywhere.
        """
        ...

    def embed(self, texts: Sequence[str]) -> list[Embedding]: ...
