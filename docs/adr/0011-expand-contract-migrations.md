# ADR-0011: Expand/contract migrations — deploy order is not guaranteed

**Status:** Accepted
**Date:** 2026-08-01

## Context

`.github/workflows/migrate.yml` runs `alembic upgrade head` against
production on every push to `main` that touches
`alam/persistence/migrations/**`, gated by its own `concurrency` group. The
Vercel deploy of `api/index.py` (`vercel.json`) fires from Vercel's own git
integration on push to `main`, entirely outside this repo's two GitHub
Actions workflows (`ci.yml`, `migrate.yml`). Neither workflow depends on, is
depended on by, or waits for the other.

That means, for any given push to `main` that changes both application code
and a migration, one of two orderings can happen, unpredictably:

- **Migration lands first.** New code deploys against an already-migrated
  schema. Fine, if the migration was written for this.
  Not fine if the *previous* deployed code (still serving requests during
  the gap) queries or writes in a way that new schema breaks — e.g. a
  dropped column the still-live old code still selects.
- **Deploy lands first.** New code, referencing a column or table the
  migration hasn't created yet, starts serving requests against the old
  schema. Any code path exercising the new column 500s until the migration
  catches up.

There is no window here that's provably short — `migrate.yml` is a full CI
job (checkout, `uv sync`, alembic) and Vercel's build/deploy pipeline is a
separate, independently-timed process. Assuming they land close together in
practice is exactly the kind of assumption that holds until the day it
doesn't.

## Decision

**Every migration must be safe against the currently-deployed code, in both
directions, for the entire window between the two pipelines finishing.**
Concretely: a migration may never assume the code deploy has already
happened, and a code deploy may never assume its migration has already run.

This is the standard expand/contract pattern, applied because the ordering
guarantee that would let you skip it does not exist in this deployment
topology (unlike, say, a single atomic deploy step that runs migrations
in-process before serving traffic).

**Rules:**

1. **Additive first.** A migration that adds a column, table, or index must
   make the new thing optional from the schema's perspective — nullable, or
   with a `server_default` — so the *previous* release's code (which knows
   nothing about it) keeps working unmodified against the new schema.
2. **Backfill separately from the add.** Populating a new column for
   existing rows is its own migration or a one-off script, never bundled
   into the same deploy as code that requires the backfill to be complete.
3. **Switch reads only after both the schema change and at least one full
   deploy cycle have landed.** Code that starts reading a new column must
   ship in a release that assumes the migration already ran — which means
   waiting one release cycle after the additive migration merged, not
   bundling both in the same PR.
4. **Drop in a later release still.** Removing a column, changing its
   nullability to `NOT NULL`, or renaming anything is a *contract* step. It
   is only safe once no deployed code — including whatever is mid-rollback
   or mid-rollout — still reads or writes the old shape. Treat "drop or
   rename in the same PR as the code that stops needing it" as a bug, not a
   simplification.
5. **Renames are two migrations, never one.** `ALTER TABLE ... RENAME
   COLUMN` is a contract-phase operation wearing an additive-phase
   disguise: it looks like a schema step, but it breaks any code — the
   currently-deployed release, mid-flight requests — still referencing the
   old name, immediately, with no grace window. Add the new column,
   dual-write, backfill, switch reads, drop the old column: five steps, not
   one `RENAME`.

A migration that only adds nullable columns, new tables, or new indexes
concurrently is always safe regardless of which pipeline wins the race. A
migration that drops, renames, or tightens a constraint is never safe to
ship in the same release as the code change that motivates it.

## Worked example, on a real table

`media_items.attributes` (`alam/persistence/models/media_item.py:60-68`) is
an unvalidated JSONB column holding book-specific metadata — author, ISBN,
page count, publisher — by explicit design (ADR-0003). Suppose a future
change wants `author` promoted to a proper indexed column, because M6
recommendations need to query or join on it and JSONB extraction in a hot
path is the exact cost ADR-0003 flagged as acceptable only because nothing
queried inside `attributes` yet.

Under this ADR, that is five releases, not one:

1. **Expand.** Migration adds `media_items.author` as `VARCHAR, NULLABLE`,
   no default needed since it starts empty. Deployed code in this release
   still reads and writes only `attributes->>'author'`; the new column is
   inert. Safe under either pipeline ordering — old code doesn't know the
   column exists, new code (if it deployed first) doesn't touch it yet.
2. **Dual-write.** Code that creates or updates a `MediaItem` writes
   `author` to *both* `attributes` and the new column. Reads still come
   from `attributes` only. Any request served by last release's code (still
   writing `attributes` only) is still correct — the new column is just
   temporarily unpopulated for rows it didn't touch, which the next step
   fixes.
3. **Backfill.** A one-off script (or job) sets `media_items.author` from
   `attributes->>'author'` for every existing row. Runs independently of
   any code deploy — it's a data migration against already-expanded schema,
   not a schema migration.
4. **Switch reads.** Code that reads a `MediaItem`'s author switches from
   `attributes->>'author'` to the `author` column. This release requires
   step 1–3 to have already landed and settled — which is guaranteed by
   virtue of being a later release, not by anything in this deploy.
   Dual-write continues, so a rollback to the previous release is still
   correct.
5. **Contract.** Once no deployed release still reads `attributes->>'author'`
   (confirmed by the fact that step 4 shipped and nothing rolls back past
   it), a final migration can stop dual-writing into `attributes['author']`
   and, if desired, drop the JSONB key or leave it as an inert historical
   artifact. `author` may also be tightened to `NOT NULL` here, now that
   backfill guarantees every row has a value.

Five deploys is more ceremony than one `ALTER TABLE ... RENAME`, but the
one-step version has a failure mode this topology cannot rule out: if the
migration lands before the code that dual-writes, or the code lands before
the migration that adds the column, there is a real window — of unknown,
unbounded length — where production is actively broken, not just
momentarily inconsistent.

## Consequences

**Positive.** No migration can take the site down mid-deploy regardless of
which of the two independent pipelines finishes first. Rollback of a code
deploy stays safe by construction, since schema is always a superset of
what any recently-deployed code needs.

**Negative.** Every non-additive schema change costs multiple PRs and
multiple release cycles instead of one. This is real overhead for a
single-user project where "just take a five-minute maintenance window"
would otherwise be a legitimate, much cheaper option — the cost this ADR
pays is the price of not having (or wanting to build) the deploy
orchestration that would make a coordinated single-step migration safe.

## Alternatives considered

**Add an explicit ordering dependency between `migrate.yml` and the Vercel
deploy** (e.g., a deploy hook that only fires after `migrate.yml`
succeeds). Rejected for now: it would remove the need for this ADR
entirely, but it means taking on deploy orchestration this project has
deliberately avoided so far (ADR-0007 already chose `pg_cron`-driven
draining over a standing worker for the same reason — less infrastructure
to own). Revisit if expand/contract's per-change overhead becomes the
project's actual bottleneck rather than a theoretical one.

**Accept the race and fix incidents as they occur.** Rejected: the failure
mode is a production 500 on a single-user system with no staging
environment to catch it first — the cheapest time to prevent this class of
bug is in the migration-writing habit, not in an incident afterward.
