"""``FakeCatalogProvider``. The only implementation used in tests — no
network, no API keys (rule 8), enforced the same way
``tests/test_providers.py`` already enforces it for the AI provider fakes.

Same three properties ``ai/providers/fakes.py`` establishes: deterministic
(same title/author always produces the same result), observable (records
every call), controllable (can be told to fail, or to return queued
results including ``None`` — a real "not found" case).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alam.catalog.provider import CatalogMetadata


@dataclass
class CatalogFetchCall:
    title: str
    author: str | None


@dataclass
class FakeCatalogProvider:
    responses: list[CatalogMetadata | None] = field(default_factory=list)
    """Queued results, popped in order. An entry of ``None`` simulates a
    real "no catalog match" result, distinct from an empty queue (which
    falls back to ``_default_metadata`` instead)."""

    fail_with: Exception | None = None
    calls: list[CatalogFetchCall] = field(default_factory=list)

    def fetch_metadata(self, *, title: str, author: str | None) -> CatalogMetadata | None:
        self.calls.append(CatalogFetchCall(title=title, author=author))

        if self.fail_with is not None:
            raise self.fail_with

        if self.responses:
            return self.responses.pop(0)
        return self._default_metadata(title)

    @staticmethod
    def _default_metadata(title: str) -> CatalogMetadata:
        return CatalogMetadata(
            blurb=f"A fake blurb for {title}.",
            subjects=["fake-subject"],
            series=None,
        )
