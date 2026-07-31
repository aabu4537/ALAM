# ADR-0004: Reading progress model

**Status:** Accepted
**Date:** 2026-07-31

## Context

Progress is the backbone of the system. Spoiler filtering, memory watermarks,
prediction windows, and briefings all key off knowing where the user is. If
progress data is wrong or stale, the spoiler architecture becomes decoration.

Two problems. First, manual progress entry is friction people abandon within a
week. Second, EPUB structure is not trustworthy: spine items are not chapters.
Real files contain front matter, part dividers, acknowledgements, and chapters
split across multiple documents. If the user also reads in paperback or audio,
the numbering may not align with the file at all.

## Decision

**Progress is captured as part of the recording act.** Before recording a voice
note, the user selects book and chapter — one tap, with the phone already in
hand. There is no separate "update my progress" surface to forget about.
Chapter granularity is sufficient; page-level precision buys nothing the
ordinal filter needs.

**Progress is stored as an ordinal plus a normalized 0–1 float** on
`reading_sessions.current_ordinal`. The ordinal is authoritative for filtering;
the float exists for display and for future media types where structure units are
coarse.

**EPUB structure is extracted, then verified by a human before indexing.**
The ingestion flow is:

1. Parse the EPUB and propose a structure.
2. Show a preview: proposed units, labels, ordinals, first lines of each.
3. Allow merge, split, relabel, and exclusion of front and back matter.
4. User confirms.
5. Only then assign final ordinals and index content chunks.

**Spine order is a hypothesis, not the answer.** Nothing may be indexed against
unverified structure.

**Sessions are separate from media items**, many-to-one. Re-reads create new
sessions. `status` includes `abandoned` as a first-class value — a DNF at 30% is
one of the strongest preference signals available and must never be deleted.

## Consequences

**Positive.** Verification costs about a minute per book and removes the single
largest source of silent wrongness in the system. Capturing progress inside the
recording flow means the data stays fresh without discipline. The ordinal
abstraction means audio or paperback reading works identically — the user picks
a chapter, and whether that maps to a file is irrelevant to the filter.

**Negative.** Verification is a UI surface that must exist before any indexing
can happen, which puts it on the M1 critical path. If the user reads a book in a
format where they do not know the chapter number, capture degrades — acceptable,
since they can select the previous known chapter and be conservative, which
fails safe.

**Open.** Whether Kindle is the primary reading platform is unresolved. If so,
the clippings file becomes a supplementary alignment source and this ADR should
be revisited.

## Alternatives considered

**Percentage-based progress only.** Rejected: percentages do not map cleanly to
content chunks, and chunk boundaries are chapter-aligned by ADR-0002.

**Trusting EPUB spine order.** Rejected. Tested against real files, it is wrong
often enough to corrupt the one key everything depends on.

**Automatic progress detection** (reading-app integration, OCR of a page). Out of
scope and dependent on platforms we do not control.
