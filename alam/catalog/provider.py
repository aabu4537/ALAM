"""``CatalogProvider`` Protocol: bibliographic metadata for a book by title
and author. One method, deliberately — this is what unblocks recommendation
explanations and briefings from being taste-only (ADR-0014, ADR-0015), not
a general media-provider abstraction (``media/base.py`` stays deferred).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class CatalogMetadata(BaseModel):
    model_config = {"frozen": True}

    blurb: str | None
    """A short description, if the catalog has one. ``None`` means the
    catalog entry exists but carries no description — distinct from the
    book not being found at all (``fetch_metadata`` returns ``None`` in
    that case)."""

    subjects: list[str]
    """Open Library's own field name, used deliberately rather than
    inventing ``genre`` — subjects are broader and messier than a genre
    taxonomy, and renaming them would imply a normalization this provider
    doesn't do."""

    series: str | None


@runtime_checkable
class CatalogProvider(Protocol):
    def fetch_metadata(self, *, title: str, author: str | None) -> CatalogMetadata | None:
        """``None`` means the catalog has no entry matching this
        title/author — a real, negative result, not an error. Callers
        (``services/catalog_backfill.py``) record that distinctly from
        "never checked," so a backfill doesn't retry the same miss forever.
        """
        ...
