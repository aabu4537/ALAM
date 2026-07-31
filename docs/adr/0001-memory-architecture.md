# ADR-0001: Three-tier memory architecture

**Status:** Accepted
**Date:** 2026-07-31

## Context

ALAM's central claim is that it remembers and connects the user's thoughts over
time. The naive implementation — write every interaction to one table, embed it,
retrieve top-k — degrades badly. At a few thousand undifferentiated rows,
retrieval precision collapses and the companion starts feeling random rather
than perceptive. "Everything becomes a memory" is a retrieval-quality bug
wearing a feature's clothes.

We also need the profile ("prefers unreliable narrators") to be available on
every request, not something we hope vector search surfaces.

## Decision

Three tiers with different storage and access patterns.

**L1 — Working memory.** The current session's context. Postgres, short-lived,
verbatim. No Redis until something forces it.

**L2 — Episodic memory.** The `memories` table. Discrete events extracted from
captures: predictions, opinions, emotional reactions, confusions, character
judgments, favorite moments, meta-comments. Fixed enum with an `other` escape
hatch, so extraction accuracy is measurable. One capture fans out to many
memories. Rows carry a vector embedding, a tsvector, and a denormalized
`structure_ordinal`.

**L3 — Semantic profile.** The `preference_facts` table. Derived by a nightly
consolidation job. Low-cardinality, human-readable, each fact carrying a
confidence score and pointers to the episodic memories that produced it.

**L3 has no embedding column and is not retrieved by vector search.** It is small
enough to load wholesale into every prompt.

We embed the *canonicalized statement*, not the raw transcript. "The narrator is
concealing his brother's death" retrieves well; forty seconds of um-laden speech
does not.

Preference evolution: `effective_confidence = base_confidence × decay(last_reinforced_at)`,
exponential with roughly an 18-month half-life. Reinforcement increments
`observation_count` and moves confidence asymptotically toward 1. Contradictions
are handled by writing a *new* fact with `supersedes_id` pointing at the old one;
the old row is retained with `superseded_at` set and is never deleted.

## Consequences

**Positive.** Because the profile is always in context, retrieval only has to
supply specifics rather than reconstruct who the user is on every query — a
large reduction in both prompt complexity and failure modes. Because superseded
facts persist with timestamps, taste drift becomes queryable for free: "through
2024 you bounced off slow openings; since March you've rated three of them five
stars." That is a differentiating product feature falling out of a schema
choice.

**Negative.** Three tiers is more schema than one table, and consolidation is an
additional job with its own failure modes. Deletion must cascade correctly:
removing a book must remove derived memories, embeddings, and any profile facts
whose evidence is now empty. The evidence pointers on L3 exist partly to make
this tractable.

**Follow-on.** Extraction quality is now the critical path for the entire
product, since every memory flows through one funnel. This raises the priority
of the M3 evaluation harness.

## Alternatives considered

**Single flat vector table.** Simpler to build, and correct for a demo. Rejected
because the degradation is not gradual — precision falls off a cliff once
several books' worth of reflections accumulate, which is exactly when the
product is supposed to start being good.

**Embedding the profile and retrieving it.** Rejected as unnecessary. The profile
is small by construction; retrieving it introduces a way for the system to
forget who the user is.

**Summarize-and-replace consolidation** (collapsing old memories into summaries
and discarding originals). Rejected because it destroys the evidence trail and
makes taste drift unrecoverable. Storage is not our constraint.
