# ADR-0007: Serverless worker execution on free-tier infrastructure

**Status:** Accepted
**Date:** 2026-07-31
**Supersedes:** [ADR-0005](0005-deployment-topology.md) in part — the FastAPI
web service row, the worker process row, and the "no free tier that spins down"
rule. The PWA on Vercel, Postgres and Storage on Supabase, deploy-at-M0, and
demo mode as a first-class requirement all still stand.

## Implementation status (as of 2026-08-01)

**Decided and implemented, accurately:** everything this ADR actually
decided — `jobs.claimed_at`/`lease_expires_at`, the reclaim predicate, the
bounded `drain(max_jobs, budget_seconds)` shape, `POST /internal/jobs/drain`
behind a bearer secret, `NullPool` + `prepare_threshold=None` under the
transaction pooler, migrations run from CI rather than in-function. All
verified directly against `jobs/runner.py`, `jobs/queue.py`,
`persistence/session.py`, and `.github/workflows/migrate.yml`.

**Inherited claims this ADR didn't verify and reality has since
contradicted:** the "still stand" list above (carried from ADR-0005)
includes "Postgres and Storage on Supabase." Postgres, yes. Storage, no —
audio is a `LargeBinary` column in Postgres itself
(`captures.audio_data`), not Supabase Storage; see ADR-0005's own
implementation-status note. "The PWA on Vercel" also still stands only as
an intention — no PWA exists yet (M7). Neither gap originates in this
ADR's own decision; both are cases of restating an earlier ADR's claim
without re-checking it against what actually got built.

## Context

The deployment target changed to **Vercel + Supabase**, and M0 must be
deployable at **$0/month**.

ADR-0005 anticipated the Vercel fork and rejected it for one narrow, still-valid
reason: the job queue (rule 5) is a long-lived process polling
`SELECT ... FOR UPDATE SKIP LOCKED`, and Vercel has no always-on process to host
one.

It also set a rule this ADR breaks: *"No free tier that spins down. A cold start
of thirty-plus seconds loses the reader."* That rule was written to protect the
six-minute portfolio evaluator. **At M0 there is no evaluator to lose.** Demo
mode does not exist until M6, and there is no public URL worth clicking until it
does. Paying for warm infrastructure through four milestones to protect a reader
who cannot yet arrive is the wrong trade. The rule is not wrong; it is early.

What makes $0 achievable is a detail ADR-0005 never examined: the assumption
that the **trigger** and the **queue** must live in the same place. They do not.
The queue is already in Postgres. Only the thing that wakes it up needs a home,
and Postgres can do that itself.

The relevant free-tier facts, verified 2026-07-31:

| | Free tier reality |
|---|---|
| Vercel Hobby function duration | **300s** with Fluid Compute (60s without) |
| Vercel Hobby cron | **once per day**, fired anywhere within the hour |
| Vercel Hobby licence | non-commercial use only |
| Supabase Free | 500 MB database, 1 GB storage, 5 GB egress, 2 projects |
| Supabase Free pause | after **7 days with no API requests** — data retained, manual resume |
| `pg_cron` / `pg_net` | available on **all plans, including Free** |
| `pg_cron` granularity | down to **1 second** |
| `pg_net` default timeout | 1–2s, per-call configurable |

The single decisive line is the second one. Vercel Cron on Hobby cannot drain a
queue — a daily trigger with an hour of jitter is not a scheduler. **This is the
only thing in the design that would have required Vercel Pro**, and it is
avoidable, because `pg_cron` is free, more precise, and already sitting next to
the queue.

## Decision

**No always-on worker, no paid tier for M0. The queue is drained by bounded,
cron-triggered invocations on a schedule owned by Postgres.**

### The trigger is Supabase Cron

| | Vercel Cron (Hobby) | Supabase Cron (Free) |
|---|---|---|
| Granularity | once per day, ±1 hour | every 1–59 seconds |
| Cost to get useful | Vercel Pro | $0 |
| Location | Vercel project config | the database the queue is in |
| Portability | Vercel-specific | plain `pg_cron`, moves with the Postgres |

`pg_cron` calls `POST /internal/jobs/drain` on a short interval. Choosing this
over Vercel Cron is what keeps the entire M0 deployment free, and it happens to
be the more portable option as well — the schedule travels with the database
rather than the host.

### Drains are bounded, not open-ended

Each invocation is explicitly capped:

```
drain(max_jobs: int, budget_seconds: float) -> DrainResult
```

- stops claiming new work once `budget_seconds` elapses, then returns cleanly
- never claims more than `max_jobs` in one invocation
- the budget sits **well under Vercel Hobby's 300s ceiling** — roughly 25s by
  default, so a single slow handler cannot walk the invocation into a kill

Frequent small drains beat rare large ones here. A short budget keeps every
invocation far from the platform limit, keeps `pg_net`'s response bookkeeping
honest, and means the scheduler interval — not the function ceiling — sets
throughput. Raising throughput later is a configuration change, not a redesign.

### Correctness never depends on the HTTP response

`pg_net` is fire-and-forget with a 1–2 second default timeout, so the caller
will routinely record a timeout for a drain that is still working. The response
is therefore **advisory only**. Its timeout is set above the drain budget for
observability, but nothing reads it to decide what happened.

What guarantees progress is the lease, below. If the trigger is late, lost,
duplicated, or times out, the queue is unaffected: work is claimed under
`SKIP LOCKED` and released by expiry, not by anything the scheduler believes.
This is what makes an unreliable free-tier trigger acceptable.

### A claim is a lease, not a flag

**This is the load-bearing consequence and the reason this ADR must land before
the `jobs` table is written.** An always-on worker that crashes is observable —
the process dies and gets restarted. A function killed at its duration ceiling
is not. A job it had claimed would stay `running` forever and never retry:
silent, permanent loss, with nothing raising an error.

So:

- `claimed_at` and `lease_expires_at` on `jobs`
- the claim predicate reclaims expired leases:
  `status = 'pending' AND run_after <= now()`
  **OR** `status = 'running' AND lease_expires_at < now()`
- the lease comfortably exceeds the drain budget, so a job in progress is never
  stolen from an invocation still working on it

### The queue abstraction is unchanged

Deliberately, so the free tier is a deployment choice rather than an
architecture:

```
jobs/queue.py    claim / complete / fail — SKIP LOCKED. Knows nothing about hosting.
jobs/runner.py   drain(max_jobs, budget_seconds). Platform-agnostic.
jobs/loop.py     while True: drain(...)      <- local dev, or any always-on host
api/routers/internal.py   POST /internal/jobs/drain -> runner.drain()
```

Moving to paid infrastructure later means raising two numbers, or running
`loop.py` on a box and deleting the cron entry. No queue rewrite, no handler
changes, no migration.

### Supporting requirements

**Connections.** Vercel functions connect through Supabase's **transaction
pooler** (port 6543), requiring `NullPool` — the app must not hold pooled
connections — and disabled prepared statements (`prepare_threshold=None` for
psycopg3), because the pooler swaps the underlying connection and a stored plan
then does not exist. Local development and `loop.py` still want a real pool, so
this is settings-driven, not hardcoded.

**Migrations** run from CI against Supabase after a successful deploy. A
serverless function is the wrong place for Alembic, and CI already holds
credentials.

**The drain endpoint is public** and requires a shared-secret bearer token.
Without one, anyone can spin the queue — which on a metered free tier is a
denial-of-wallet as much as a correctness problem.

## Consequences

**Positive.** M0 through at least M2 costs nothing, on infrastructure that can
be upgraded without touching application code. No always-on instance to pay for,
patch, or babysit during the long stretches a single-user system spends idle.
Lease expiry delivers crash recovery that an always-on design would have
deferred to M2 and probably gotten wrong. And overlapping drains become the
*normal* case rather than a hypothetical, which makes M0's two-worker
no-double-claim test load-bearing in production and not merely in CI.

**Negative — the pause.** A Supabase Free project pauses after 7 days without
API requests, and resuming is manual. Whether a `pg_cron` job firing every few
seconds counts as activity is **not confirmed** — the documented criterion is
API requests, and internal cron activity may not qualify. Do not assume the
drain keeps the project alive. Verify during Session 5; if it does not, the
fallback is a scheduled request against the API surface, and the real fix is
Supabase Pro before demo mode ships.

**Negative — latency.** Job latency is bounded below by the cron interval.
Acceptable for asynchronous processing of a voice note, unacceptable for
anything interactive — which V1 does not have, per ADR-0002's note on removing
synchronous in-reading conversation.

**Negative — the ceilings are real, and M3 is where they bite.** 500 MB is
comfortable for M0–M2 and starts to matter once M3 writes embeddings and content
chunks. Vercel Hobby is non-commercial only, which is fine for a portfolio piece
and forecloses nothing until ALAM stops being one. A handler that cannot finish
inside the drain budget — plausibly M2 transcription — needs a provider with
webhook callbacks rather than a synchronous wait, or a paid tier. That is a real
constraint on M2's provider choice and should be weighed when the STT
implementation is picked, not discovered afterwards.

**Explicitly deferred.** The paid posture — warm instances, no pause, headroom —
is a Session 5 configuration change plus a plan upgrade, to be made **before
demo mode goes public at M6**, which is the first moment ADR-0005's original
argument applies.

## Alternatives considered

**Vercel Cron.** The obvious choice, and the one that costs $20/month. Hobby's
once-daily trigger with an hour of jitter cannot drain a queue at all, so it
forces Pro purely to buy per-minute scheduling that `pg_cron` provides free at
1-second resolution. Rejected on cost and on coupling — it would also move the
schedule into Vercel config.

**Vercel Workflows or Queues.** Genuinely capable and the right answer for a
team already committed to Vercel, as ADR-0005 said. Rejected for lock-in, for
cost, and because the Postgres queue already exists and is already tested.

**Supabase Edge Functions as the worker.** Closest to the data, free-tier
friendly, no Vercel involvement. Rejected because they run Deno/TypeScript and
every handler here is Python; it would split extraction across two languages to
save one HTTP hop.

**An external free cron service** (cron-job.org and similar) pinging the drain
endpoint. Works, and would sidestep the Supabase pause question by generating
outside traffic. Rejected as a third vendor in the critical path for something
Postgres already does — but worth reconsidering *specifically* as pause
mitigation if `pg_cron` turns out not to count as activity.

**Keep one always-on box just for the worker.** Cheapest in latency, simplest
conceptually, and the thing this ADR exists to avoid. Rejected: it reintroduces
a second platform, a second deploy pipeline, and a monthly bill to run a process
that is idle almost all the time.

**Stay on Render.** Still defensible, and ADR-0005's reasoning for it was sound.
Superseded because the platform and the cost constraint were both decided
outside this ADR's scope, not because Render was wrong.
