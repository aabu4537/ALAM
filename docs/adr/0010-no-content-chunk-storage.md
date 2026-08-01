# ADR-0010: Decline content-chunk / raw-book-text storage

**Status:** Accepted
**Date:** 2026-08-01

## Context

`content_chunks` has been a named-but-unbuilt table since M3 (ADR-0008) and
was deferred again at M5 for the identical reason (ADR-0009): it would store
chunked raw text from the media item itself, and nothing in this codebase has
ever ingested full book text to chunk. `alam/media/books/epub.py` parses an
EPUB into per-chapter units, but only `label` and a short `first_lines`
preview snippet are persisted (`media_structure_units.first_lines`,
`alam/persistence/models/media_structure_unit.py:61`) — the chapter body
itself is discarded after parsing. There is no raw-text column, table, or
blob store anywhere in `alam/persistence/`.

M6's three deliverables — spoiler-safe pre-book briefings, reading-journey
summaries, recommendations with explanations (`docs/milestones.md`, M6) — do
not require chapter text to produce. A briefing needs catalog metadata
(blurbs, themes, series relationships — things `media_items.attributes`
JSONB already has a slot for, per ADR-0003). A journey summary needs the
reader's own memories, already retrievable via `retrieve_memories`
(`alam/ai/retrieval/hybrid.py:34`). A recommendation needs the preference
profile (`get_taste_drift`, `alam/services/taste_drift.py:40`) plus catalog
metadata for candidate books. None of these read the book's prose.

ALAM's retrieval model has been, since M3, retrieval over what the *reader*
said about the book — the memories tier — not retrieval over the book's own
text. `alam/ai/retrieval/hybrid.py:8-11` states this scoping explicitly.
`content_chunks` would be a second, structurally different retrieval system
(full-text search or embeddings over publisher-owned prose, not
reader-owned reflections) bolted onto a project whose core loop has never
needed one.

## Decision

Do not build `content_chunks`, chapter-text storage, or any full-text
ingestion pipeline for M6.

M6's knowledge sources are: `media_items.attributes` (catalog metadata,
type-specific, unvalidated at the DB layer per ADR-0003), `memories` (via
existing hybrid retrieval), `preference_facts` (via `get_taste_drift`), and
`predictions` (via `list_predictions_for_book`). All four already exist and
are read-accessible per the retrieval-surface inventory in
`docs/milestones/M6-open-questions.md`.

Where M6 needs metadata ALAM doesn't have yet (a blurb, a theme list, a
series relationship), that is a `media/books/` provider-fetch concern — a
`MediaProvider.fetch_metadata` implementation populating `attributes` — not
a content-ingestion concern. It is a smaller, different build than chunking
a book's full text.

## Consequences

**Positive.** No new ingestion subsystem, no chunking pipeline that has to
respect `media_structure_unit` boundaries (CLAUDE.md rule 2), no second
embedding side table (`chunk_embeddings`, anticipated but never built —
ADR-0008 line 30) to design and maintain. No copyright exposure from storing
and serving back verbatim excerpts of copyrighted book text — a real
liability difference between "search the reader's own words" and "search
the publisher's text," and one this project has no legal review budget for.
M6 stays scoped to code paths that already exist and are already tested.

**Negative.** A pre-book briefing or a recommendation's "why" cannot quote
or reason over the book's actual prose — only over its metadata and the
reader's own memories about other books. A journey summary is inherently
self-consistent with this limitation (it summarizes the reader's own
memories, which is exactly what's stored), but a briefing that wants to say
something like "this opens similarly to the book you read last spring" is
making that claim from metadata and memory similarity, not from having read
either book itself.

## Revisit if

**In-text Q&A over a specific chapter** — a feature where the user asks
"what happened in chapter 12?" or "remind me who Yueh is" and expects an
answer grounded in the book's actual prose, not the reader's own reflection
about it. That is the concrete trigger this ADR names in advance: it cannot
be built from `memories` (a reader's reflections are not the book's text)
or from `attributes` (catalog metadata is not chapter content). Building it
requires exactly the `content_chunks` table, chunking pipeline, and
`chunk_embeddings` side table this ADR declines to build now — at that
point, ADR-0008's side-table pattern applies directly and CLAUDE.md rule 2
(chunks never cross a `media_structure_unit` boundary) governs the schema.

## Alternatives considered

**Build `content_chunks` now, as groundwork for M6.** Rejected: no M6
deliverable reads it, per the milestone DoD. Building storage ahead of a
consumer is exactly the failure mode ADR-0003 already named for media
abstraction ("abstracting over exactly one implementation reliably produces
the wrong abstraction") — the same reasoning applies to building a chunking
pipeline ahead of the one feature that would shape its chunk size, overlap,
and retrieval strategy.

**Store full chapter text without chunking, as a single `TEXT` column on
`media_structure_units`.** Rejected on the same copyright-exposure grounds
as chunking, without even the retrieval benefit — an unchunked column can't
be searched or embedded meaningfully at chapter granularity, so it would
exist for months as a liability with no working feature attached to it.
