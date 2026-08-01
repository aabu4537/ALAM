"""Bibliographic metadata lookup (M6 session 3, ADR-0015).

Not ``ai/providers/`` — this isn't a model capability with cost or
instrumentation concerns, it's a lookup against a free, keyless catalog API.
Not ``media/base.py`` either — that stays deferred (M6 audit,
``docs/milestones/M6-open-questions.md`` §1); this is metadata-fetch only,
not the full ``search``/``fetch_metadata``/``normalize_progress``
``MediaProvider`` shape.

Same Protocol+fake discipline CLAUDE.md rule 8 establishes for LLM/
embedding/STT providers, for the same reason: tests never touch the
network, real implementations swap in behind one resolver.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.catalog.fakes import FakeCatalogProvider
from alam.catalog.provider import CatalogMetadata, CatalogProvider
from alam.config.settings import get_settings

if TYPE_CHECKING:
    from alam.config.settings import Settings

__all__ = [
    "CatalogMetadata",
    "CatalogProvider",
    "FakeCatalogProvider",
    "get_catalog_provider",
]


def get_catalog_provider(settings: Settings | None = None) -> CatalogProvider:
    settings = settings or get_settings()
    if settings.catalog_provider == "fake":
        return FakeCatalogProvider()
    if settings.catalog_provider == "open_library":
        # Imported here, not at module level, so importing this package —
        # which every test does — never pulls in the real implementation
        # for the (overwhelmingly common) "fake" path. No paid-provider gate:
        # Open Library is free and keyless, same treatment ai/providers'
        # local/ollama/faster_whisper kinds already get.
        from alam.catalog.open_library import OpenLibraryCatalogProvider

        return OpenLibraryCatalogProvider()
    raise ValueError(f"unknown catalog provider: {settings.catalog_provider!r}")
