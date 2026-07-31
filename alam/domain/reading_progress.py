"""Pure ordinal math for reading progress (ADR-0004).

No I/O — testable in milliseconds, per CLAUDE.md rule 3.
"""

from __future__ import annotations


def compute_progress(ordinal: int, total_units: int) -> float:
    """Normalized 0-1 position. ``ordinal`` is 1-based; ``total_units`` is the
    count of structure units currently persisted for the book.

    Clamped rather than raising on an out-of-range ordinal. ``ordinal`` is
    authoritative for filtering and is stored separately — this value is only
    ever for display, so a caller racing a structure re-verification should
    see a sane number rather than a crash.
    """
    if total_units <= 0:
        raise ValueError("total_units must be positive")
    return max(0.0, min(1.0, ordinal / total_units))
