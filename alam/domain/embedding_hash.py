"""Content hash for embedding idempotency (ADR-0008). Pure — no I/O.

Computed before an embedding provider is ever called: a hit against an
existing ``memory_embeddings`` row with this hash means the same
``(content, model, version)`` triple has already been embedded, so both the
provider call and the insert are skipped. What makes a resumable backfill
cheap to interrupt and re-run.
"""

from __future__ import annotations

import hashlib


def embedding_content_hash(*, content: str, embedding_model: str, embedding_version: str) -> str:
    """A separator between fields, not concatenation — otherwise
    ``("ab", "c")`` and ``("a", "bc")`` under the same model/version would
    hash identically."""
    digest_input = "\x1f".join((content, embedding_model, embedding_version))
    return hashlib.sha256(digest_input.encode()).hexdigest()
