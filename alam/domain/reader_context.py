"""``ReaderContext``: the reader's position, scoped to one media item.

A retrieval function that takes a bare ``current_ordinal: int`` trusts every
caller to have looked up the right one for the right book. Nothing in Python
stops a caller from constructing this dataclass directly, but the one
production path — ``services.reading_sessions.get_reader_context`` — reads it
off the media item's active ``ReadingSession``, which a caller cannot
fabricate. Retrieval functions take a ``ReaderContext`` as a single unit
rather than ``media_item_id`` and ``current_ordinal`` as separate parameters,
so the two can never be paired incorrectly (an ordinal from one book applied
to another's id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid


@dataclass(frozen=True, slots=True)
class ReaderContext:
    media_item_id: uuid.UUID
    user_id: uuid.UUID
    current_ordinal: int
