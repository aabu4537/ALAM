# ADR-0005: Deployment topology

**Status:** Accepted
**Date:** 2026-07-31

## Context

ALAM must be publicly reachable — it is a portfolio artifact as well as a
personal tool. Vercel was the assumed target.

Vercel's function durations are no longer the obstacle they once were; with
Fluid Compute, Node and Python functions can run well past the point where
transcription and extraction would finish. The obstacle is structural: the job
queue (ADR-0001, rule 5) is a long-lived process polling
`SELECT ... FOR UPDATE SKIP LOCKED`. Vercel has no always-on process to host
that. Adapting would mean either cron-triggered queue draining or Vercel
Workflows — both viable, both coupling the backend's execution model to one
vendor.

A second constraint arrived with the portfolio goal: the evaluator is someone
who clicks a link, spends about six minutes, and leaves. They will not sign in.

## Decision

**Split deployment.**

| Layer | Platform |
|---|---|
| Next.js PWA | Vercel |
| FastAPI web service | Render or Fly.io |
| Worker process | Render or Fly.io (same repo, separate service) |
| Postgres + pgvector | Supabase |
| Audio blobs | Supabase Storage |

**No free tier that spins down.** A cold start of thirty-plus seconds loses the
reader. Budget the paid entry tier.

**Deploy in M0, not M7.** The health endpoint and one live worker ship to the
real URL before any feature exists. Deployment problems found at M0 cost an
afternoon; found at M7 they end the project.

**Demo mode is a first-class requirement.** A synthetic reader persona with a
year of history, seeded via the same generator that solves cold start, reachable
with no authentication. Demo responses are precomputed rather than live
inference — this caps API spend at zero for public traffic and is faster, which
matters more than richness for a six-minute skim.

**The owner's real data is separated from demo data by `user_id` and must never
be reachable from demo mode.** Voice reflections about books get personal in ways
that are easy to underestimate.

## Consequences

**Positive.** The backend stays portable and vendor-neutral, which is both better
engineering and a better interview answer. Continuous deployment from M0 means no
big-bang release. Precomputed demo responses make the public surface free to run
and fast to load.

**Negative.** Two platforms instead of one, so two sets of environment variables
and two deploy pipelines. Cost moves from zero to roughly $0–15/month. The demo
persona is real work that produces nothing for the owner's personal use — though
it doubles as the cold-start solution, which is why it is not pure overhead.

## Alternatives considered

**All-Vercel with cron-drained queue.** Replace the worker loop with a scheduled
function that drains the queue. Rejected: couples the execution model to the
platform, and reasoning about concurrency and retries gets harder, not easier.

**All-Vercel with Workflows.** Genuinely capable, and the right answer for a
team already committed to Vercel. Rejected here for lock-in and because the
worker loop is already designed and simpler.

**Single VPS running everything.** Cheapest and most portable. Rejected because
it means owning TLS, deploys, backups, and uptime — time better spent on the
product.
