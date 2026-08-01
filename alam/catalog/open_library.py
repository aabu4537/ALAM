"""Open Library-backed ``CatalogProvider`` (M6 session 3, ADR-0015), called
directly over Open Library's free, keyless REST API with ``httpx`` rather
than any SDK — same reasoning
``alam/ai/providers/real/voyage_embeddings.py`` gives (a couple of JSON
endpoints don't need one).

**Written against Open Library's published API shape, not verified against
a live call — this environment has no network access.** Confirm the
response shapes below against a real request before the first real run:

- ``GET /search.json?title=...&author=...&fields=key&limit=1`` — the
  default search response does *not* include a description or subjects
  (those need an explicit ``fields=`` request or a follow-up call), only
  enough to resolve a work key.
- ``GET /works/{key}.json`` — ``description`` is either a plain string or
  ``{"type": "/type/text", "value": "..."}``; ``subjects`` is a flat list
  of strings when present.

**``series`` is always ``None`` here, not a bug.** Open Library doesn't
expose a reliable series field on a work record the way it does
``description``/``subjects`` — series membership lives in a separate,
inconsistently-populated concept. Left unset rather than guessed at from
something unreliable; ``CatalogMetadata.series`` stays in the shape for
whichever provider (or a future revision of this one) can actually source
it.
"""

from __future__ import annotations

from typing import Any

import httpx

from alam.catalog.provider import CatalogMetadata

_SEARCH_URL = "https://openlibrary.org/search.json"
_WORKS_URL = "https://openlibrary.org"


class OpenLibraryCatalogProvider:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=15.0)

    def fetch_metadata(self, *, title: str, author: str | None) -> CatalogMetadata | None:
        work_key = self._find_work_key(title=title, author=author)
        if work_key is None:
            return None

        response = self._client.get(f"{_WORKS_URL}{work_key}.json")
        response.raise_for_status()
        work = response.json()

        return CatalogMetadata(
            blurb=self._extract_description(work.get("description")),
            subjects=[str(s) for s in work.get("subjects", [])][:10],
            series=None,
        )

    def _find_work_key(self, *, title: str, author: str | None) -> str | None:
        params: dict[str, Any] = {"title": title, "fields": "key", "limit": 1}
        if author:
            params["author"] = author

        response = self._client.get(_SEARCH_URL, params=params)
        response.raise_for_status()
        docs = response.json().get("docs", [])
        if not docs:
            return None
        key = docs[0].get("key")
        return str(key) if key else None

    @staticmethod
    def _extract_description(raw: object) -> str | None:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            value = raw.get("value")
            if isinstance(value, str):
                return value
        return None
