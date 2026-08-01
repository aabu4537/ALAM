"""Local sentence-transformers-backed ``EmbeddingProvider`` (M5.5a task 2).

Fits the existing Protocol without changes. Downloads and caches the model
from Hugging Face on first use — real network I/O, which is exactly why
this class is never constructed by the unit test suite (see the package
docstring).

Unlike Voyage's hardcoded dimension lookup (no live API to query from this
environment), sentence-transformers reports its own loaded model's output
width directly — nothing to verify against external docs here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sentence_transformers import SentenceTransformer

from alam.ai.providers.embeddings import Embedding

if TYPE_CHECKING:
    from collections.abc import Sequence


class LocalEmbeddingProvider:
    def __init__(self, *, model: str) -> None:
        self.model_name = model
        self.version_name = "1"
        self._model = SentenceTransformer(model)

        dimensions = self._model.get_embedding_dimension()
        if dimensions is None:
            raise ValueError(f"sentence-transformers model {model!r} reports no output dimension")
        self._dimensions: int = int(dimensions)

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

        vectors = self._model.encode(list(texts), normalize_embeddings=True)

        return [
            Embedding(
                vector=vector.tolist(),
                model=self.model_name,
                version=self.version_name,
                dimensions=self._dimensions,
            )
            for vector in vectors
        ]
