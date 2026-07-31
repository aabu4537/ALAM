"""Retry backoff. Pure functions — no clock, no I/O, no randomness.

The caller supplies the current time and the random draw. That is what keeps
this testable in microseconds without freezing a clock or seeding a global RNG,
and it is the reason ``domain/`` forbids I/O (CLAUDE.md rule 3).
"""

from __future__ import annotations

DEFAULT_BASE_SECONDS = 2.0
DEFAULT_FACTOR = 2.0
DEFAULT_CAP_SECONDS = 3600.0


def backoff_seconds(
    attempt: int,
    *,
    base_seconds: float = DEFAULT_BASE_SECONDS,
    factor: float = DEFAULT_FACTOR,
    cap_seconds: float = DEFAULT_CAP_SECONDS,
) -> float:
    """Delay before retrying a job that has failed ``attempt`` times.

    ``attempt`` is 1-based: the delay after the first failure is
    ``base_seconds``. Growth is exponential, clamped at ``cap_seconds`` so a
    job that has been failing for a day is still retried hourly rather than
    drifting to a delay measured in weeks.
    """
    if attempt < 1:
        raise ValueError(f"attempt must be >= 1, got {attempt}")

    delay = base_seconds * (factor ** (attempt - 1))
    return min(delay, cap_seconds)


def with_jitter(delay_seconds: float, random_unit: float) -> float:
    """Spread retries so simultaneous failures do not retry in lockstep.

    Equal jitter — half the delay is fixed, half is scattered — rather than
    full jitter, which can return a near-zero delay and retry a failing job
    almost immediately. ``random_unit`` is a draw from ``[0, 1)``, passed in
    so this stays pure.
    """
    if not 0.0 <= random_unit < 1.0:
        raise ValueError(f"random_unit must be in [0, 1), got {random_unit}")
    if delay_seconds < 0:
        raise ValueError(f"delay_seconds must be >= 0, got {delay_seconds}")

    half = delay_seconds / 2.0
    return half + (half * random_unit)
