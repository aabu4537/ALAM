"""Confidence math for L3 preference facts (ADR-0001).

Pure, no I/O — the same reason ``domain/reading_progress.py`` and
``domain/spoiler_filter.py`` are pure (CLAUDE.md rule 3): the profile's
believability rests on a formula, not a model call, so it must be testable in
milliseconds and auditable by reading it.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt

HALF_LIFE_DAYS = 548.0
"""ADR-0001: "exponential with roughly an 18-month half-life." 18 * 30.44."""


def effective_confidence(
    *, base_confidence: float, last_reinforced_at: dt.datetime, now: dt.datetime
) -> float:
    """``base_confidence x decay(last_reinforced_at)`` (ADR-0001).

    An unreinforced fact fades rather than staying permanently believed — a
    preference observed once three years ago should carry less weight today
    than one observed last month, without ever being deleted (taste drift
    stays queryable; see ADR-0001's "summarize-and-replace" rejection).
    """
    elapsed_days = (now - last_reinforced_at).total_seconds() / 86400
    decay = math.pow(0.5, elapsed_days / HALF_LIFE_DAYS)
    return base_confidence * decay


def reinforce(*, base_confidence: float, observation_count: int) -> tuple[float, int]:
    """A new observation of the same preference: increments
    ``observation_count`` and moves confidence toward 1, asymptotically
    (ADR-0001) — each additional observation closes a shrinking fraction of
    the remaining distance to 1, the way one more data point matters less
    once a pattern is already well established. Never reaches or exceeds 1.
    """
    new_observation_count = observation_count + 1
    step = (1.0 - base_confidence) / (new_observation_count + 1)
    return base_confidence + step, new_observation_count
