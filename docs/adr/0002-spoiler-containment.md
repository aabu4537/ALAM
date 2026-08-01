# ADR-0002: Spoiler containment

**Status:** Accepted
**Date:** 2026-07-31

## Implementation status (as of 2026-08-01)

**Decided and implemented:** Layer 1 — `domain/spoiler_filter.py`'s
`is_visible`/`filter_visible`, enforced as an index-only SQL predicate in
`persistence/repositories/retrieval.py` and re-checked as defense-in-depth
after RRF fusion in `ai/retrieval/hybrid.py`. Layer 4 — `alam/eval/spoiler_eval.py`
exists, runs in CI, and reads `leakage_rate=0.0` as expected — but at
**10 adversarial cases**, not the "roughly 200" this ADR names as the
target. The mechanism is real; the scale is not there yet.

**Decided, not implemented:** Layer 2 (a system prompt stating the reader's
current position) and Layer 3 (a second-pass classifier checking a draft
response against retrieved-but-excluded content) — neither exists, because
neither has a caller yet. Both apply to a *synthesis response*
(a briefing, a journey summary, a recommendation's explanation), and no
such response is generated anywhere in the codebase — that's M6
(`docs/milestones.md`), not built. This ADR's "Negative" consequences
section already anticipated this ("Layer 3 adds a model call and latency
to every synthesis response") without flagging that no such response
existed yet to add it to.

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
