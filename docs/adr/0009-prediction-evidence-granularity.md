# ADR-0009: Prediction evidence is memories, not content chunks

**Status:** Accepted
**Date:** 2026-07-31

## Context

`docs/milestones.md`'s M5 definition of done was written against a table that
does not exist: "resolution triggered when progress crosses
`made_at_ordinal + N`, scanning only chunks in that window" and "evidence
chunk linking" both assume `content_chunks`. It was deliberately deferred at
M3 (ADR-0008) — no chunking pipeline exists, and more fundamentally, no raw
chapter text is stored anywhere yet. `media_structure_units.first_lines` is a
short preview snippet for the structure-verification UI (ADR-0004), not full
chapter text. Building `content_chunks` for M5 would mean building book-text
ingestion and a boundary-respecting chunker (CLAUDE.md rule 2) first — a
substantially larger undertaking than prediction lifecycle logic itself, and
not something M5's own scope calls for on its own merits.

## Decision

Predictions resolve against `memories`, the L2 tier that already exists and
that M3's hybrid retrieval already operates on exclusively (`ai/retrieval/
hybrid.py` made the same call for the same reason). A prediction's evidence
window is `structure_ordinal` in `(made_at_ordinal, made_at_ordinal +
resolution_window]` over memories for the same media item — the reader's own
recorded reactions in the chapters between when the prediction was made and
when its window closes, not the book's raw text.

This is not a lesser substitute so much as the more honest source of
evidence for this feature specifically: a prediction is confirmed or refuted
by what the *reader* subsequently says about what happened, filtered through
their own reflections, not by re-deriving it from prose ALAM would have to
re-read and interpret itself. It also keeps prediction resolution inside the
memories tier's spoiler-safety properties for free — evidence memories are
already `structure_ordinal`-bounded by construction.

## Consequences

**Positive.** No new ingestion subsystem. Resolution quality is bounded by
how much the reader actually reflects on relevant chapters — the same honest
limitation the M3 eval harness already surfaces for retrieval, not a new one.

**Negative.** A prediction whose payoff chapter got no voice reflection has
no evidence to resolve against. The resolution service treats an empty
evidence window as `unresolvable` without an LLM call — not a failure, the
correct outcome when there's nothing to weigh a prediction against.

**Revisit when:** `content_chunks` gets built for retrieval (M6 synthesis is
the milestone likely to need book text directly). At that point prediction
resolution could additionally scan chunks in the window, but memories should
stay in the evidence set even then — they are what makes a resolution about
this reader's prediction rather than a generic plot-consistency check.

## Alternatives considered

**Build `content_chunks` now, inside M5.** Rejected — raised to the user
explicitly rather than decided silently, since it triples M5's scope into a
text-ingestion project. Declined in favor of shipping M5 on the schema that
exists today.

**Block M5 entirely until chunking exists.** Rejected. Nothing about
prediction lifecycle, the confirmed/refuted/unresolvable outcome, or evidence
linking as a concept requires chunk-level text — only the DoD's literal
wording did.
