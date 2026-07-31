# ADR-0003: Media abstraction

**Status:** Accepted
**Date:** 2026-07-31

## Context

ALAM is intended to eventually cover movies, TV, games, podcasts, and articles.
Books are the first module. The stated goal is that adding a module should not
require architectural change.

The failure mode here is well known: abstracting over exactly one implementation
reliably produces the wrong abstraction. You discover the correct seam by
building the second module, not by imagining it. But deferring *all* generality
means a books-shaped schema that has to be torn up later.

## Decision

Build the **seams**, not a plugin system.

**Schema.** One `media_items` table with a `media_type` discriminator and a
JSONB `attributes` column for type-specific metadata. No per-type tables.

**Structure.** One `media_structure_units` table with an `ordinal`, a
`unit_type` (`chapter`, `episode`, `scene`, `segment`), and a label. A chapter
for books, an episode for TV, a scene or timestamp bucket for film. **The
ordinal is the universal ordering key** and is what every spoiler, timeline, and
prediction query operates on. This is the real abstraction; everything else is
bookkeeping.

**Code.** A `MediaProvider` Protocol in `media/base.py` with three methods:
`search`, `fetch_metadata`, `normalize_progress`. Exactly one implementation:
`media/books/`. Roughly 200 lines total.

**Progress.** Normalized to a 0–1 float plus an ordinal, per ADR-0004.

Everything else — memory, retrieval, profile, prediction lifecycle, job queue —
is media-agnostic already and touches only ordinals and `media_item_id`.

## Consequences

**Positive.** Adding a second module means writing one `MediaProvider`
implementation and populating `media_structure_units` differently. No changes to
memory, retrieval, or profile code. The extensibility claim is demonstrable
rather than asserted, at a cost of a few hundred lines.

**Negative.** JSONB `attributes` is unvalidated at the database level; type-safety
must be enforced in Pydantic models at the boundary, and it is easy to let that
slip. Querying inside `attributes` is more awkward than a typed column would be
— acceptable, because we do not query book-specific metadata in hot paths.

**Explicitly not built.** No plugin registry, no dynamic module loading, no
abstract base classes with one subclass, no `MediaType` strategy hierarchy.
A Protocol and a discriminator column are sufficient.

## Alternatives considered

**Per-type tables** (`books`, `movies`, …) with a shared parent. Rejected:
joins everywhere, and every media-agnostic query becomes polymorphic.

**Full plugin architecture** with registration and dynamic dispatch. Rejected as
premature generalization for zero current users of the extension point.

**Books-only schema, generalize later.** Rejected because `media_structure_units`
and the ordinal key are cheap now and would be a painful migration once memories,
chunks, and predictions all reference them.
