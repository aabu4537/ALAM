"""Pure ordinal math for prediction resolution (M5).

No I/O — testable in milliseconds, per CLAUDE.md rule 3. Resolution scans
only the memories in a bounded window after a prediction was made
(docs/milestones.md, M5), never the whole future, so the window bounds
themselves are the one piece of "prediction" logic worth pulling out of the
service and testing in isolation.
"""

from __future__ import annotations


def is_due_for_resolution(
    *, made_at_ordinal: int, resolution_window: int, current_ordinal: int
) -> bool:
    """True once the reader's progress has reached or passed the ordinal the
    prediction's window closes at."""
    return current_ordinal >= made_at_ordinal + resolution_window


def evidence_window(*, made_at_ordinal: int, resolution_window: int) -> tuple[int, int]:
    """The inclusive ``structure_ordinal`` range to scan for evidence:
    strictly after the prediction was made (excludes the prediction's own
    source memory from being its own evidence) through the window's close."""
    return made_at_ordinal + 1, made_at_ordinal + resolution_window
