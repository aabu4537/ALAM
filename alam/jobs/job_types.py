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

CONSOLIDATE_PREFERENCES = "consolidate_preferences"
"""Triggered weekly by Supabase Cron calling POST
/internal/preferences/consolidate (ADR-0001, M4) — the schedule itself is
provisioned in Supabase, not in this repo, same as the drain schedule
(ADR-0007). Re-enqueues itself for the same user while their backlog is
full, then moves to the next user with an unconsolidated memory, until none
remain."""

RESOLVE_PREDICTIONS = "resolve_predictions"
"""Enqueued by ``services.capture_submission`` every time a capture advances
a reading session's ``current_ordinal`` (M5, ADR-0009) — that is exactly the
moment "progress crosses `made_at_ordinal + N`" can become true for some
pending prediction on that book. Checks all of that book's pending
predictions and resolves the ones whose window has closed; does not chain,
since one book's pending-prediction count is small enough to finish in a
single invocation."""

FETCH_CATALOG_METADATA = "fetch_catalog_metadata"
"""Triggered on demand (POST /internal/catalog/backfill), not chained from
anywhere — a one-time catch-up over existing media items missing
``attributes["catalog"]`` (M6 session 3, ADR-0015), same resumable
cursor/re-enqueue shape ``EMBED_MEMORIES_BACKFILL`` uses. Re-enqueues
itself with an advanced cursor until the batch it claims comes back short
of the configured size."""
