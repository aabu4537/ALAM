# ADR-0002: Spoiler containment

**Status:** Accepted
**Date:** 2026-07-31

## Implementation status (as of 2026-08-01, updated for M6 session 1)

**Decided and implemented:** Layer 1 — `domain/spoiler_filter.py`'s
`is_visible`/`filter_visible`, enforced as an index-only SQL predicate in
`persistence/repositories/retrieval.py` and re-checked as defense-in-depth
after RRF fusion in `ai/retrieval/hybrid.py`. Layer 4 — `alam/eval/spoiler_eval.py`
exists, runs in CI, and reads `leakage_rate=0.0` as expected — but at
**10 adversarial cases**, not the "roughly 200" this ADR names as the
target. The mechanism is real; the scale is not there yet.

**Decided and implemented, see ADR-0013:** Layer 2 (a system prompt stating
the reader's current position) and Layer 3 (a second-pass classifier
checking a draft response against retrieved-but-excluded content). Both
were "Decided, not implemented" as of 2026-08-01's initial version of this
section, because neither had a caller — no synthesis response existed
anywhere in the codebase yet. `alam/services/journey_summary.py` (M6
session 1) is that first caller: `ai/prompts/journey_summary.py` states the
reader's position explicitly (Layer 2), and `ai/synthesis/leak_check.py`
checks the generated draft against the exact memory content the ordinal
filter excluded from it (Layer 3), via a schema-constrained classifier
call, not a second freeform generation. ADR-0013 records the design and
the rationale for shipping Layer 3 now rather than staying deferred: Layer
1's `leakage_rate=0.0` measures retrieval, not generation, and M6 is the
first milestone where a model generating prose from only-permitted input
can still leak a future event by inference. `synthesis_leakage_rate`
(`alam/eval/journey_summary_eval.py`) is the corresponding Layer 4 case.
This ADR's "Negative" consequences section already anticipated the Layer 3
cost ("adds a model call and latency to every synthesis response") without
flagging that no such response existed yet to add it to — that gap is now
closed.

## Finding (2026-08-01): the four-layer claim was never retrofitted onto routes that predate it

This ADR and Layer 1's implementation landed in the **M3** commit
(`aa9b2c5`, 2026-07-31 21:07). Two reader-facing routes were built **before**
that commit and were never revisited once Layer 1 existed to apply to them:

- `GET /books/{id}/structure` — built in **M1** (`70f95d9`, 2026-07-31
  17:24), roughly 3.5 hours before Layer 1 existed. Returned every
  structure unit unconditionally, including `first_lines` (up to 240
  characters of the book's own raw prose) and chapter `label`s, regardless
  of reading position. This one predates Layer 1 outright — not a gap
  introduced by a later change, a gap that was simply never closed when
  Layer 1 arrived.
- `GET /books/{id}/predictions` — built in **M5** (`33cae2d`, 2026-07-31
  22:11), after Layer 1 existed but not built to use it. Fixed by
  ADR-0012 (2026-08-01, `8fc13ec`).

Both were found the same way: not by a leakage number going wrong (Layer 4's
adversarial set never covered either route, so it had nothing to catch this
with), but by an explicit audit of every listing/read function for a
legitimate reason to be unfiltered. **`/structure` was the older gap, found
second.** Fixed the same day as `/predictions`: `GET /books/{id}/structure`
is now the verification-only read (refuses once
`structure_verified_at` is set), `GET /books/{id}/chapters` is the new,
`ReaderContext`-scoped reading read, and `first_lines` was removed from the
reading read's response model entirely rather than filtered — see the
`api/routers/books.py` module docstring. `GET /books/{id}/captures/{id}`
had the identical missing-ordinal-check shape (narrower reachability — a
capture id must already be known to the caller — but the same pattern) and
was closed in the same pass.

**The invariant going forward:** every reader-facing route that returns
media-derived content (memories, predictions, structure/chapters, captures —
anything keyed to a `media_item_id` with a position in the book) takes a
`ReaderContext`, resolved server-side, never from a request parameter. A
route that legitimately needs unfiltered access (the verification read,
while unverified; a future export feature) is an explicit, documented
exemption, not a route nobody got around to checking.

This is enforced, not just stated: `tests/test_reader_context_coverage.py`
enumerates every registered route and asserts each one either depends on
`api.dependencies.reader_context_dependency` or appears on that test's
exemption list, with a reason attached to each exemption. A new route that
returns book content and forgets the dependency fails that test, not a
future audit.

## Context

The original requirement read "the AI must NEVER spoil future content." That is
not achievable and should not be claimed. The language model has the book in its
weights; no amount of retrieval filtering removes that. Every mitigation is
probabilistic.

This is not a reason to drop the feature. It is the most interesting engineering
problem in the project, and it is the one where an honest, measured answer reads
as more competent than a confident guarantee.

## Decision

Restate the requirement as **a measured leakage rate under defense in depth**,
and build four layers.

**Layer 1 — Data.** Every memory and every content chunk carries a
`structure_ordinal`. Retrieval filters with `WHERE structure_ordinal <= :current`.
This is deterministic, cheap, index-backed, and delivers most of the value.
It is the reason `structure_ordinal` is denormalized onto `memories`.

**Layer 2 — Prompt.** The system prompt states the user's current position and
the constraint explicitly.

**Layer 3 — Output.** A cheap second-pass classifier checks the draft response
against the content that was *retrieved but excluded by the ordinal filter*.
Checking against the excluded set is what makes this tractable — we are asking a
narrow question, not "is this a spoiler in general."

**Layer 4 — Evaluation.** An adversarial test set of roughly 200 hand-labeled
cases, run in CI, producing a leakage rate. The number goes in the README.

Chunking follows from this: **content chunks never cross a structure unit
boundary**, because a chunk spanning chapters 7 and 8 cannot be filtered and
poisons the whole scheme. The spoiler boundary dictates the chunking strategy,
not the other way around.

## Consequences

**Positive.** Layer 1 is deterministic and testable without any model in the
loop, so the majority of the guarantee is covered by fast unit tests over pure
functions in `domain/`. The eval harness produces a concrete number, which is
the single most credible thing the project can show.

**Negative.** Layer 3 adds a model call and latency to every synthesis response.
Layers 2 and 3 can never be made perfect against parametric knowledge — the
README must say so plainly. Layer 1 is only as good as the ordinal data, which
makes ADR-0004's verification step load-bearing rather than optional.

**Note.** Removing synchronous in-reading conversation from V1 substantially
shrinks the spoiler surface. It now matters for pre-book briefings and
between-session questions, not for live chat.

## Alternatives considered

**Prompt-only containment.** Rejected. Untestable, unmeasurable, and fails
silently in exactly the cases that matter most.

**Refusing to discuss the current book at all.** Technically safe, product-dead.

**Claiming a guarantee in the README.** Rejected on honesty grounds and because
it is trivially falsifiable by anyone who tries.
