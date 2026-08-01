# ADR-0008: Embedding storage — side tables, not columns

**Status:** Accepted
**Date:** 2026-07-31

## Context

CLAUDE.md rule 7 requires every table with an embedding to also carry
`embedding_model` and `embedding_version`, so "model migrations are
incremental, never stop-the-world." M3 is the first milestone that actually
computes an embedding, for `memories` first and `content_chunks` later.

The obvious schema is an `embedding vector(N)` column directly on `memories`,
alongside `embedding_model`/`embedding_version` columns. It does not deliver
what rule 7 promises. pgvector's `vector(N)` fixes the dimension `N` at
column-definition time — every row in that column must be the same width.
The moment the configured model changes to one with a different dimension (a
near-certainty over the life of a personal project; embedding models are not
pin-compatible across providers or even across a provider's own versions),
the column cannot hold both the old and the new vectors at once. Migrating
means adding a column, re-embedding every row in one pass, and cutting over —
exactly the stop-the-world migration rule 7 exists to rule out. It also
forecloses the thing an eval harness (this milestone's own DoD) most wants:
running two models side by side long enough to compare their retrieval
quality before committing to one.

## Decision

Embeddings live in a side table, one per embedded entity: `memory_embeddings`
now, `chunk_embeddings` when `content_chunks` exists. Four properties, all in
service of the same goal — a model swap is an `INSERT`, not a migration.

**Natural key `(memory_id, embedding_model, embedding_version)`, enforced by a
unique constraint.** One row per memory per model per version. Two models can
have live rows for the same memory simultaneously — that is the whole point:
backfilling a new model does not require deleting or racing the old one.

**The vector column carries no fixed dimension.** Declared as pgvector's bare
`vector` type, not `vector(N)`. A `vector(N)` column is what makes a
same-table design fail here — one column, one width, no coexistence. Without
a fixed width, a row from a 1536-dimension model and a row from a
768-dimension model live in the same table without conflict. Every query
scopes to one `(embedding_model, embedding_version)` pair before it ever
reaches the `<=>` comparison operator, so mismatched dimensions never meet at
query time either — pgvector would reject the comparison, but the query
structure never lets it happen.

**`content_hash` — `sha256(content ‖ embedding_model ‖ embedding_version)`,
unique.** A backfill computes this before calling the embedding provider. A
hit means this exact content has already been embedded under this exact
model and version, so both the provider call and the insert are skipped.
This is what makes a killed-and-restarted backfill (see the job design below)
and a re-run against an already-fully-embedded table cost nothing —
re-processing lands on the same hash and stops immediately.

**No ANN index.** `<=>` runs as a brute-force scan, no HNSW or IVFFlat.
CLAUDE.md is explicit that this is a single-user system, not built for
horizontal scale — a personal reading history tops out at a few thousand
memories even after years of use, and an exact scan over that many rows costs
low milliseconds with no tuning, no recall loss, and no index rebuild after
every backfill batch. Revisit if a real workload disagrees.

## Consequences

**Positive.** A model swap is additive: backfill the new model's rows,
compare recall against the old model's rows with the eval harness, flip a
settings default, and only then decide whether to drop the old rows.
Idempotent backfill is nearly free to implement — a unique index does the
work a service would otherwise have to.

**Negative.** Every retrieval query is a join (`memories` ⋈
`memory_embeddings`) filtered to the current `(embedding_model,
embedding_version)`, not a same-table read. Storage carries a `memory_id` and
two string columns per model tracked per memory — irrelevant at this scale.
`content_hash` must be computed by one shared function everywhere it is
checked or produced; two implementations drifting apart silently breaks the
dedup guarantee.

**Cost of not deciding now.** Schema decisions are the expensive kind to
unwind in this project (see ADR-0006's own accounting of that cost), and an
embedding column is exactly the default an engineer reaches for without
pricing in a future model swap. Deciding the pattern here, before
`content_chunks` exists to repeat the same mistake, is cheaper than
retrofitting it onto two tables instead of documenting it once.

## Alternatives considered

**`vector(N)` directly on `memories`.** Rejected for the reason above: fixes
dimension at migration time, forces a stop-the-world re-embed on any model
change.

**Unconstrained `vector` directly on `memories` (no side table).** Solves the
dimension problem but not the coexistence problem — one row per memory still
means only one model's embedding can exist at a time. The side table's real
value is the `(memory_id, model, version)` key, which the same-table design
cannot express.

**An HNSW index from the start.** No workload justifies the recall/tuning
tradeoff at personal-library scale. Exact search is simpler, always correct,
and adding an index later is a normal migration — nothing about deferring it
is a one-way door.

**`content_hash` over `(model, version)` without the text.** Would dedupe
across genuinely different content that happened to share a model and
version, which is wrong, not just imprecise — the hash has to include the
content for "already embedded" to mean what it claims.
