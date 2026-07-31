# ADR-0006: Ordinal stability and structure re-verification

**Status:** Accepted
**Date:** 2026-07-31

## Context

Two accepted decisions are in tension, and the conflict is invisible until the
system has been in use for a while.

[ADR-0002](0002-spoiler-containment.md) makes `structure_ordinal` a denormalized
integer on every row that needs spoiler filtering, so the filter stays an
index-only predicate. `CLAUDE.md` rule 1 states this is deliberate and must not
be normalized away.

[ADR-0004](0004-reading-progress-model.md) allows a human to merge, split,
relabel, and exclude structure units during verification, on the premise that
EPUB spine order is a hypothesis rather than the answer. It also expects people
to get this wrong on a first pass — that is the entire reason the verification
step exists.

Combined, these permit a silent corruption. If a book's structure is re-verified
after memories, chunks, or predictions already reference it, every denormalized
`structure_ordinal` on those rows still holds the *old* numbering. Nothing
errors. The rows are simply wrong from that moment on, and they are wrong in the
one column the spoiler filter trusts. The failure surfaces as the system
mentioning something the reader has not reached — the exact outcome the whole
architecture exists to prevent.

The denormalized integer is the right call for read performance and the wrong
thing to key referential integrity on. It carries no identity: ordinal `7` after
a renumber is a different chapter than ordinal `7` before it, with no way to
tell from the value.

## Decision

**Carry both.** Every table that references a structure unit stores:

- `structure_ordinal` — a plain `INTEGER`, denormalized, **the only column the
  spoiler filter reads**. Rule 1 is untouched.
- `structure_unit_id` — a `UUID` foreign key to `media_structure_units.id`,
  which is stable across any renumbering.

The ordinal does the filtering. The FK does the bookkeeping. Neither takes on
the other's job.

This makes re-verification a recomputable operation rather than a corruption:

```sql
UPDATE memories m
   SET structure_ordinal = u.ordinal
  FROM media_structure_units u
 WHERE u.id = m.structure_unit_id
   AND m.structure_ordinal <> u.ordinal;
```

Two supporting constraints make that safe:

**`UNIQUE (media_item_id, ordinal)` is `DEFERRABLE INITIALLY IMMEDIATE`.**
Postgres checks unique constraints per row, not per statement, so a bulk shift
such as `SET ordinal = ordinal + 1` transiently collides and aborts under an
immediate constraint. Deferring inside the renumbering transaction lets the
intermediate state exist and be checked once at commit.

**`media_structure_units.id` is never reused.** A merge or split writes new
units; it does not recycle an existing id under new meaning. Re-pointing a
memory at a merged unit is an explicit `UPDATE` of `structure_unit_id`, which
means the recompute above then fixes the ordinal for free.

Because the FK is `ON DELETE RESTRICT`, deleting a structure unit that still has
memories attached fails loudly rather than orphaning them.

## Consequences

**Positive.** Re-verification becomes a supported operation instead of a
one-way door, which matters because ADR-0004 openly expects first-pass structure
to be wrong. The spoiler filter's hot path is unchanged — it still reads one
indexed integer and never joins. The FK also makes the cascade-deletion problem
raised in ADR-0001's negative consequences tractable: "remove a book and
everything derived from it" is now a graph the database can walk.

**Negative.** Sixteen bytes per row and one additional index, on the largest
tables in the system. Two columns describing one relationship can drift if
anything writes `structure_ordinal` without writing `structure_unit_id`; the
recompute query above is the reconciliation, and it should be run as an
assertion in tests rather than trusted to discipline.

**Cost of not deciding it now.** `media_structure_units` ships in the first
migration. Adding the FK later means backfilling it across live memory rows with
no reliable way to recover which unit an ordinal *used* to mean — the
information needed to repair the data is exactly what was lost.

## Alternatives considered

**Immutable ordinals — structure is fixed once confirmed.** Simplest schema, no
FK, no deferrable constraint. Rejected because it makes a mis-verified book
permanently mis-verified, and ADR-0004 exists precisely because first-pass
structure extraction is unreliable. It converts a correctable mistake into a
reason to delete and re-ingest the book, losing every memory attached to it.

**FK only, drop the denormalized ordinal.** Correct in the relational sense, and
rejected by rule 1 for a stated reason: the spoiler filter would need a join on
the hottest path in the system, and ADR-0002 leans on that predicate being
index-only.

**Reconcile with a trigger.** Would keep the two columns consistent
automatically. Rejected as hidden control flow — the recompute belongs in a
verification service where it is visible and testable, not in database logic
that no test exercises directly.
