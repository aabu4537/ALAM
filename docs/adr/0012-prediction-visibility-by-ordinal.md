# ADR-0012: Prediction visibility is scoped by ordinal, not by reading session

**Status:** Accepted
**Date:** 2026-08-01

## Context

`GET /books/{id}/predictions` (`services/predictions.py`'s
`list_predictions_for_book`) originally returned every prediction ever made
for a book, unfiltered — no ordinal check on `made_at_ordinal`, no check on
whether a resolved prediction's outcome was safe to reveal. `Prediction` rows
are keyed to `media_item_id` only; `reading_sessions` are many-to-one against
a media item, and ADR-0004 already establishes that a re-read creates a new
session rather than reusing or replacing the old one. Nothing scoped a
prediction to the session that made it.

**Worked example: a re-read.** A reader finishes *Dune* once. Along the way,
at `made_at_ordinal=5`, they recorded "I bet Paul kills the Baron Harkonnen" —
a prediction with `resolution_window=10`. By ordinal 15 of that first read,
the resolution job (`services/prediction_resolution.py`) had evidence and
resolved it `CONFIRMED`. The session ends `COMPLETED`. Months later the
reader starts a re-read: a new `ReadingSession`, `current_ordinal` back at 1.
By ordinal 7 they've reached the chapter where the prediction was originally
made — its statement is fair to show, they said it themselves at this point
in the book. But `GET /books/{id}/predictions` also shows `status: confirmed`
and the evidence memory that named how the Baron actually dies, both drawn
from ordinal 12 of the *first* read — eight ordinals past where this second
read currently stands. The reader spoiled their own re-read by opening a
screen that had nothing to do with reading further.

This is a real gap in ADR-0002's "four-layer spoiler containment enforced in
SQL" claim: `predictions` was outside Layer 1's guarantee entirely, because
Layer 1 was written and enforced against `memories` and never extended to
this table when M5 added it.

## Decision

**Prediction visibility is a pure function of `(prediction, current_ordinal)`,
never of which reading session created or resolved the row.**

Two ordinal gates, applied in `services/predictions.py` via a `ReaderContext`
(the same value object and the same `get_reader_context` construction path
`GET /books/{id}/memories` already uses — see the ReaderContext hardening
work this ADR follows):

1. **Existence.** A prediction is included in the response at all only if
   `made_at_ordinal <= current_ordinal` (`domain.spoiler_filter.is_visible`).
   One made further ahead than the reader has (this read-through) reached is
   omitted outright — its very existence is a spoiler.

2. **Outcome.** A prediction that passes gate 1 renders its *real* `status`
   and evidence only once `current_ordinal >= made_at_ordinal +
   resolution_window` — the same threshold
   `prediction_resolution.is_due_for_resolution` uses to decide when to
   actually run resolution
   (`domain.spoiler_filter.visible_prediction_status`). Below that threshold
   it always renders `pending` with no evidence, regardless of what the
   stored `status` actually is. This is what makes the worked example above
   safe: at ordinal 7 of the re-read, gate 1 passes (the statement shows) but
   gate 2 does not (7 < 5 + 10 = 15), so the response shows `pending`, no
   evidence — exactly what a first-time reader at ordinal 7 would see, even
   though the database has known the real answer for months.

**This is deliberate, not an approximation of session-scoping.** The
alternative — scoping by `reading_session_id`, showing a re-read only
predictions made *during that session* — was considered and rejected. It
would suppress `made_at_ordinal=5`'s prediction entirely on the re-read until
the reader re-states it, which is wrong: it's the same book, the same
prediction, and the reader is entitled to see it again exactly when they
reach the same point, whether or not they choose to voice it a second time.
Ordinal-scoping reproduces the first read's reveal schedule on every
subsequent read of the same book, which is the correct behavior for a
personal spoiler-safety tool — a re-reader relives the book's reveals in
order, not a session-fresh blank slate and not the first read's full
hindsight.

## Consequences

**Positive.** One definition of "safe to show," reusable by any future
prediction-consuming surface (M6 briefings, when built) without re-deriving
it. No schema change — `made_at_ordinal + resolution_window` is already
stored and is exactly the ordinal resolution itself waits for, so "safe to
reveal" and "due for resolution" share one threshold by construction rather
than two thresholds that could drift apart.

**Negative.** `GET /books/{id}/predictions` now requires an active reading
session (via `get_reader_context`), matching `GET /books/{id}/memories`'s
existing gating exactly. A book with no active session — finished, with no
re-read in progress — will 404 rather than returning full history, which is
a behavior change from before this ADR. Whether "current position" should
instead fall back to the most recent session regardless of status (so a
finished book still shows its full, now-unlocked history) is a real,
separate design question this ADR does not resolve — flagged here rather
than decided silently.

## Alternatives considered

**Scope by `reading_session_id`.** Rejected above — wrong reveal schedule for
a re-read.

**Add a stored `resolved_at_ordinal` column, set at resolution time.**
Rejected as unnecessary: `made_at_ordinal + resolution_window` is already the
exact ordinal resolution fires at (`is_due_for_resolution`'s own threshold),
so a stored column would only duplicate a value already fully determined by
existing fields — a second source of truth for the same number, with no
corresponding new information.

**Mask evidence content but show the real status.** Rejected — a status of
`confirmed`/`refuted` is itself the spoiler; showing it while hiding
supporting text still tells the reader the outcome, just without the
receipts.
