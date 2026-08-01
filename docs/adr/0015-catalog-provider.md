# ADR-0015: CatalogProvider — bibliographic metadata, and recommendations stop being taste-only where it's fetched

**Status:** Accepted
**Date:** 2026-08-01

## Context

ADR-0014 (M6 session 2) made recommendations deliberately taste-only:
every claim about a candidate is about the *reader*, never the *book*,
because `media_items.attributes` carried no blurb/genre/theme/series data
— only Goodreads CSV columns (author/ISBN/pages/publisher/rating/shelf).
ADR-0014 named this session's `CatalogProvider` as what unblocks it, and
briefings (session 4) have the identical dependency: no source for a
book's content, no spoiler-safe synthesis to write about it.

Not `media/base.py` — that stays deferred (M6 audit,
`docs/milestones/M6-open-questions.md` §1), the exact "wrong abstraction"
risk ADR-0003 itself warns against building ahead of a second real media
type. `CatalogProvider` is narrower and single-purpose: one method,
metadata fetch only, no `search`/`normalize_progress`.

## Decision

### `alam/catalog/`, not `ai/providers/`, not `media/base.py`

A new top-level module. Same Protocol+fake discipline CLAUDE.md rule 8
establishes for LLM/embedding/STT providers (tests never touch the
network, a real implementation swaps in behind one resolver), but not
placed under `ai/providers/` — this isn't a model capability with cost or
instrumentation concerns, it's a lookup against a free, keyless catalog
API. `CatalogProvider.fetch_metadata(*, title, author) -> CatalogMetadata
| None` — `blurb`, `subjects` (Open Library's own field name, not invented
`genre`), `series`. `get_catalog_provider()` mirrors
`ai/providers/__init__.py`'s resolver shape, with **no paid-provider
gate** — Open Library is free and keyless, same treatment `ollama`/
`local`/`faster_whisper` already get.

The real implementation (`alam/catalog/open_library.py`) calls Open
Library's search and works APIs directly over `httpx`, same reasoning
`ai/providers/real/voyage_embeddings.py` gives for skipping an SDK — and
carries the same disclaimer that ADR already sets a precedent for:
**written against the published API shape, not verified against a live
call**, since this environment has no network access. `series` is left
`None` unconditionally in this implementation — Open Library doesn't
expose it reliably on a work record the way it does `description`/
`subjects`, and guessing at an unreliable field would be worse than
leaving it unset.

### Caching: `attributes["catalog"]`, fetch-once, a miss is still a result

Unlike LLM-generated synthesis artifacts (journey summaries,
recommendations), bibliographic metadata for a fixed edition doesn't
change — no staleness function, just "has this been fetched at all."
`attributes["catalog"] = {"blurb", "subjects", "series", "fetched_at"}`.
Critically: **a provider miss (`fetch_metadata` returns `None`) is
recorded as a real result** — `{"blurb": None, "subjects": [], "series":
None, "fetched_at": ...}` — not left absent. A definite "checked, found
nothing" is different from "never checked," and only the latter should be
retried; without this distinction the backfill would re-fetch the same
miss on every run forever.

### Fetching: resumable job-queue backfill, not lazy in-request

Matches `services/embedding_backfill.py`'s cursor/re-enqueue shape
(ADR-0008) exactly, not a synchronous fetch bolted onto `GET
/recommendations` — this is library-wide enrichment of existing rows, the
same category as the embeddings backfill, not a per-reader on-demand
generation. `POST /internal/catalog/backfill` (drain-secret gated, same
shape as `trigger_embedding_backfill`) enqueues `FETCH_CATALOG_METADATA`,
which claims a bounded batch (`catalog_backfill_batch_size`, smaller than
the embeddings default — one HTTP round-trip per book here, no batch
endpoint to share it across), and re-enqueues itself with an advanced
cursor until a batch comes back short.

### Recommendations stop being taste-only where a candidate has been backfilled

A provider with no caller is exactly the speculative-build CLAUDE.md and
ADR-0003 both warn against, and ADR-0014 explicitly named this as what
unblocks recommendations. This session wires it in **using the same
structural discipline ADR-0014 established, not loosening it**:
`CitationRef.type` widens to `Literal["preference_fact", "memory",
"catalog"]`. A `"catalog"` citation's `id` is the candidate's own
`media_item_id` — there is exactly one catalog entry per book, unlike
facts and memories, so no separate id space is needed. There is still no
free-text field anywhere in the schema for the model to write a
characterization into; the prompt shows a candidate's fetched blurb/
subjects when present (tagged `"Known:"`) and instructs the model it may
cite `"catalog"` only for a candidate that has one, and only to reference
what's shown — for any candidate without a `"Known:"` line, the "you have
NO information about this candidate's content" instruction from ADR-0014
still applies unchanged. `domain/recommendation_groundedness.py` gains a
third valid-id set, `valid_catalog_media_item_ids` — populated only for
candidates whose fetched entry actually has content (a found-nothing
result is *not* in this set, so citing it still fails groundedness, same
severity as any other ungrounded citation). The displayed claim's text for
a `"catalog"` citation is the candidate's own stored blurb (or a subjects
summary if there's no blurb) — Open Library's text, composed by ALAM,
never the recommendation LLM's, same "ALAM composes the displayed text"
discipline ADR-0014 established for facts and memories.

`PROMPT_VERSION_ID` bumps to `"recommendations-v2"` (rule 6 — the template
text changed).

**Not touched:** journey summaries, Layer 3, `is_artifact_stale` — this
session's catalog data has no bearing on a book the reader is already
inside. Briefings (session 4) are the other real consumer of
`CatalogProvider`, left for its own session — they also need Layer 3
back, since a briefing has real excluded content to check a draft against
now that a legitimate source of book content exists.

## Consequences

**Positive.** Recommendations can now say something real about a
candidate's actual content — grounded in Open Library's own text, not
invented — for any candidate the backfill has reached, while candidates
not yet backfilled degrade gracefully to exactly session 2's taste-only
behavior rather than erroring. The structural "no field for unsourced
content" guarantee ADR-0014 established extends to the new citation type
rather than being an exception to it. A provider now has a real caller,
closing the gap ADR-0014 explicitly flagged.

**Negative.** Open Library coverage and match quality (title/author
search, no ISBN/edition disambiguation) is unverified until a real run
happens — a wrong or low-quality match would surface as a wrong "Known:"
line. `series` is always `None` from this provider — a real gap, not
silently pretended away. The backfill's one-HTTP-call-per-book shape means
a large library takes many job invocations to fully cover; acceptable for
a single-user personal library, would not scale to a multi-tenant catalog
without a real batch API.

## Alternatives considered

**Lazy, in-request fetch on first `GET /recommendations`/`GET
/books/{id}/journey-summary` read.** Rejected — adds real external-API
latency to a reader-facing read path for library-wide enrichment that has
nothing to do with any one request, and duplicates the "cached, not
fetched fresh per request" requirement the original M6 sketch already
named; the job-queue backfill gives that caching for free as a side effect
of its own resumability.

**`media/base.py` now, populated by this session's metadata-fetch need.**
Rejected — the M6 audit already resolved this specifically (§1): building
the Protocol with no second media type to validate its shape against
risks the "wrong abstraction" ADR-0003 opens by naming. Nothing about
`CatalogProvider`'s narrow, single-method shape needs the full
`search`/`fetch_metadata`/`normalize_progress` `MediaProvider` interface.

**A free-text field on the widened `Claim` schema for catalog-backed
claims, relying on groundedness alone to check it.** Rejected for the same
reason ADR-0014 rejected it the first time: an existence check on a
citation doesn't verify a claim's *content* matches what was actually
fetched. Extending the "selection, not prose" schema to the new citation
type — rather than carving out an exception for it — keeps the same
structural guarantee for every citation type, not just the original two.
