"""Voyage AI-backed ``EmbeddingProvider`` (M5.5a), called directly over
Voyage's REST API with ``httpx`` rather than the ``voyageai`` SDK — see
``pyproject.toml`` for why (one JSON endpoint doesn't need that SDK's
dependency footprint).

Fits the existing Protocol without changes: ``embed()`` maps directly onto
one POST to ``/v1/embeddings`` with a batch of texts, mirroring OpenAI's
embeddings API shape closely enough that this implementation is written
against that shape from documentation — not verified against a live call,
since this environment has no network access. Confirm the response shape
(``data[].embedding``, ``model``) against Voyage's current API reference
before the first real run.

**A real Protocol-level limitation, not fixed here per instructions:**
Voyage's API distinguishes ``input_type="document"`` (content being
indexed) from ``input_type="query"`` (a search query being embedded to
compare against it) for better retrieval quality — but
``EmbeddingProvider.embed()`` takes only a batch of texts with no way to
say which case this is, and ``ai/retrieval/hybrid.py`` calls the exact
same ``embed()`` for both indexing memories and embedding the search query.
``input_type`` is left unset here (Voyage's neutral default) rather than
hardcoded to ``"document"``, which would actively hurt query-embedding
quality. Widening the Protocol to carry this distinction is a real
follow-up, deliberately not done here.

**Dimensions are a hardcoded lookup, not queried from the API.** The
Protocol's ``dimensions`` property has to answer without an API call (it
fixes the pgvector column width at M3 setup time, read before anything is
ever embedded) — verify ``_MODEL_DIMENSIONS`` against Voyage's current
model list before relying on it; a wrong value here does not fail loudly,
it silently stores truncated or padded vectors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from alam.ai.providers.embeddings import Embedding

if TYPE_CHECKING:
    from collections.abc import Sequence

_API_URL = "https://api.voyageai.com/v1/embeddings"

_MODEL_DIMENSIONS = {
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-large-2": 1536,
    "voyage-code-2": 1536,
}
"""Verify against https://docs.voyageai.com before trusting this for a
model not already listed here."""


class VoyageEmbeddingProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.model_name = model
        self.version_name = "1"
        try:
            self._dimensions = _MODEL_DIMENSIONS[model]
        except KeyError:
            raise ValueError(
                f"unknown Voyage model {model!r}; add its output dimension to "
                "_MODEL_DIMENSIONS after checking https://docs.voyageai.com"
            ) from None

        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

    @property
    def model(self) -> str:
        return self.model_name

    @property
    def version(self) -> str:
        return self.version_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        if not texts:
            return []

        response = self._client.post(
            _API_URL, json={"input": list(texts), "model": self.model_name}
        )
        response.raise_for_status()
        payload = response.json()

        return [
            Embedding(
                vector=row["embedding"],
                model=self.model_name,
                version=self.version_name,
                dimensions=self._dimensions,
            )
            for row in payload["data"]
        ]
