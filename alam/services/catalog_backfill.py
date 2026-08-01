"""Resumable, cursor-based catalog metadata backfill (M6 session 3,
ADR-0015): one bounded batch per job invocation, chained via re-enqueue
with an advancing cursor. Same shape ``services/embedding_backfill.py``
established for ADR-0008.

Safe to be killed mid-run. The job runner commits a whole invocation's work
— every ``attributes["catalog"]`` write plus the next job's enqueue — or
none of it (``jobs/handlers.py``); there is no partially-written batch to
reconcile. A killed invocation simply never advanced the cursor, so the
next claim of this job type re-derives the same batch from
``list_missing_catalog_metadata`` and tries again.

Triggered on demand (``POST /internal/catalog/backfill``) — this is
library-wide enrichment of existing media items, not a per-reader on-demand
generation the way journey summaries/recommendations are, so it runs
through the job queue rather than synchronously in a request. See
``jobs/job_types.py``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from alam.catalog import get_catalog_provider
from alam.config.settings import get_settings
from alam.jobs.job_types import FETCH_CATALOG_METADATA
from alam.jobs.queue import JobQueue
from alam.persistence.repositories.media_items import MediaItemRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def fetch_catalog_metadata_backfill(session: Session, payload: dict[str, Any]) -> None:
    settings = get_settings()
    after_id_raw = payload.get("after_id")
    after_id = uuid.UUID(after_id_raw) if after_id_raw else None

    provider = get_catalog_provider()
    media_items = MediaItemRepository(session)

    batch = media_items.list_missing_catalog_metadata(
        after_id=after_id, limit=settings.catalog_backfill_batch_size
    )
    if not batch:
        return

    fetched_at = dt.datetime.now(dt.UTC)
    for item in batch:
        author = item.attributes.get("author")
        result = provider.fetch_metadata(title=item.title, author=author)
        media_items.set_catalog_metadata(
            item,
            blurb=result.blurb if result is not None else None,
            subjects=result.subjects if result is not None else [],
            series=result.series if result is not None else None,
            fetched_at=fetched_at,
        )

    if len(batch) == settings.catalog_backfill_batch_size:
        # A full batch means more may remain; a short one means this was the
        # last. Stopping here avoids one guaranteed-empty extra job per run.
        JobQueue(session).enqueue(
            job_type=FETCH_CATALOG_METADATA, payload={"after_id": str(batch[-1].id)}
        )
