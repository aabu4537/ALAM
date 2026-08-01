"""Job type string constants.

Split out from ``handlers.py`` so a service module can name the job type it
enqueues (or chains to) without importing the registry — ``handlers.py``
itself imports concrete handler functions from ``services/`` to register
them, and a service importing a constant back from ``handlers.py`` would be
circular.
"""

from __future__ import annotations

NOOP = "noop"

TRANSCRIBE_CAPTURE = "transcribe_capture"
"""Enqueued by ``services.capture_submission``. Chains to ``CORRECT_TRANSCRIPT``
on success."""

CORRECT_TRANSCRIPT = "correct_transcript"
"""Enqueued by the ``TRANSCRIBE_CAPTURE`` handler once a raw transcript
exists. Chains to ``EXTRACT_MEMORIES`` on success."""

EXTRACT_MEMORIES = "extract_memories"
"""Enqueued by the ``CORRECT_TRANSCRIPT`` handler once a corrected transcript
exists. The last stage of the M2 capture pipeline."""

EMBED_MEMORIES_BACKFILL = "embed_memories_backfill"
"""Triggered on demand (POST /internal/embeddings/backfill), not chained from
extraction — a one-time catch-up over existing memories, not the steady-state
embedding of new ones (ADR-0008). Re-enqueues itself with an advanced cursor
until the batch it claims comes back short of the configured size."""
