# CLAUDE.md

Operating instructions for coding agents working in this repository.
Read this file completely before making any change.

---

## What ALAM is

ALAM (Adaptive Learning Associative Memory) is a personal AI media companion.
Version 1 covers books only.

It is a **single-user personal system** that doubles as a portfolio artifact.
It is **not** a SaaS product. Do not build for multi-tenancy, horizontal scale,
or thousands of users.

The core loop: the user records a short voice reflection while reading, it is
transcribed and decomposed into typed memories, those memories consolidate into
an evolving preference profile, and the system uses both to produce
spoiler-safe insights, prediction resolutions, and recommendations.

---

## Current milestone

**M7 — Polish, complete.** M0 through M7 are all done — M7 is the last
milestone `docs/milestones.md` names. Its definition of done had three
items: frontend, observability (per-request token accounting + a cost
view), and a README rewrite with real eval numbers and an honest
limitations section. All three are closed as of session 4 below.

**Session 1 (2026-08-01) built the observability item, LLM-only** — a
scope decision made directly with the user, not a default:
`get_embedding_provider()`/`get_stt_provider()` have no equivalent
instrumentation to `llm_calls`, so a Voyage embedding call or an OpenAI
Whisper transcription (both real spend under a paid provider) are
invisible to `GET /internal/costs` and to `domain/llm_cost.py`'s pricing
table. A known, documented gap — see that module's docstring — not a
silent one; embeddings/STT instrumentation is its own future session if
complete spend accounting is wanted.

**Session 2 (2026-08-01) added owner authentication (ADR-0017)** — found to
be a prerequisite while researching what the frontend would talk to
(everything owner-scoped was reachable by anyone who found the URL).
Shared-password login, a stdlib signed `SameSite=Lax` cookie, router-level
`require_owner_session` gating, enforced structurally by
`tests/test_owner_session_coverage.py`.

**Session 3 (2026-08-02) built the frontend item — Next.js, one Vercel
project** (ADR-0018), against the owner-scoped API session 2 made safe to
point a browser at. Two small backend additions came out of building
real pages against the real API rather than guessing at its shape:
`GET /books` (no route listed the owner's library at all) and
`GET /books/{id}/chapters/first` (no route told a verified,
not-yet-started book where to begin — `/chapters` 404s until a reading
session exists, and starting one needs a real `structure_unit_id`). A
real routing bug was found and fixed during manual verification, not
guessed at: the frontend's first-cut page paths (`/books/[id]`,
`/preferences`, `/recommendations`) collided with backend router
prefixes and were silently swallowed by `vercel.json`'s/`next.config.ts`'s
rewrites before Next's own dynamic routes ever saw the request — fixed by
renaming the frontend pages (`/library/[id]`, `/profile`, `/recommended`)
so no ambiguity exists at all, not by reordering rewrites. No public
demo-mode UI was built — the earlier scope decision was owner-scoped +
auth, not demo-first, and that stands.

**Session 4 (2026-08-02) closed the last M7 item — the README rewrite.**
The real-provider eval numbers this item was thought to be blocked on
turned out to already exist: M5.5a (before M7 even started) had already
run `extraction_eval`/`retrieval_eval`/`spoiler_eval` against real local
providers (Ollama `llama3.2:3b`, `bge-small-en-v1.5` embeddings —
`docs/eval/baseline-local-providers.md`) and those numbers were already
in the README's Limitations section. What was actually stale was the
status banner and the M7 milestone-table row, both still reading "in
progress" after sessions 1-3 had already merged. Fixed as a text-only
pass — no new eval run, on the user's explicit call: the one number the
README itself flags as not-yet-real (`synthesis_leakage_rate`, Layer 3's
leak-check, which currently only exercises the fake LLM's canned
verdict) was left as a known, honestly-labeled gap rather than run
against Ollama this session. `docs/milestones.md`'s per-milestone status
markers (M3 wrongly said "current"; M4-M7 had none) were corrected to
match while in there.

Nothing outside the M7 definition of done in `docs/milestones.md` should be
implemented. If a task seems to require work this doc doesn't name, stop
and say so rather than building it.

---

## Non-negotiable rules

These are settled decisions with recorded rationale in `docs/adr/`. Do not
re-litigate them in code. If you believe one is wrong, say so in prose and wait
for a human decision.

1. **`structure_ordinal` is denormalized onto `memories` on purpose.** It exists
   so the spoiler filter is an index-only predicate. Do not normalize it away.

2. **Content chunks never cross a `media_structure_unit` boundary.** A chunk
   spanning two chapters is unfilterable and breaks spoiler containment.

3. **`domain/` is pure.** No I/O, no ORM imports, no network calls, no LLM
   calls. Only plain data in and out. This is where spoiler rules, confidence
   decay, salience scoring, and ordinal math live, and it must be testable in
   milliseconds without fixtures.

4. **No autonomous agent in V1.** The pipeline is deterministic:
   input → processing → retrieval → synthesis → memory update.
   Agents arrive when multiple knowledge sources make retrieval orchestration a
   real problem, not before. See ADR-0001. Reaffirmed, not just carried over
   by default, at M6's start (2026-08-01) — `docs/milestones.md` names M6 as
   the point to reconsider this; asked directly, answered no. Revisit only if
   a concrete orchestration problem shows up while building M6, not
   speculatively.

5. **No Celery, no Redis, no external broker.** The job queue is Postgres using
   `SELECT ... FOR UPDATE SKIP LOCKED`. Transactional enqueue is the point.

6. **Every LLM output records the prompt version id that produced it.**

7. **Every table with an embedding also carries `embedding_model` and
   `embedding_version`.** Model migrations must be incremental, never
   stop-the-world.

8. **Provider access goes through Protocols.** LLM, embeddings, and speech-to-text
   are interfaces in `ai/providers/` with fake implementations. Tests never make
   network calls.

9. **The demo persona and the owner's real data are separated by `user_id`.**
   Real reading notes are private and must never be reachable from demo mode.

---

## Do NOT build yet

This list matters more than the feature list. A design document describing the
whole system is in this repo; its presence is not permission to implement it.

- Any agent, tool-calling loop, or LangGraph (declined for M6 specifically,
  not just still-pending — see rule 4)
- `content_chunks` / raw book text ingestion or chunking (declined for M6 —
  ADR-0010; revisit only for in-text Q&A over a specific chapter)
- `media/base.py` / `MediaProvider` Protocol (deferred for M6 —
  `docs/milestones/M6-open-questions.md` question 1)
- Memory deletion or edit path (deferred for M6 — same doc, question 5)
- A public demo-mode frontend surface — M7 session 3 built the
  owner-scoped Next.js frontend only, per the earlier owner-scoped-vs-demo
  scope decision; `GET /demo/books` stays backend-only, unconsumed by any
  page, until that's revisited on purpose
- A drag-and-drop structure editor, or a full offline/background-sync PWA
  (service worker, install prompts) — the structure verify page is a
  plain editable table, and the capture recorder's IndexedDB queue only
  retries a failed upload, deliberately short of either
- Any media type other than books
- Caching layers, rate limiting, read replicas, sharding

---

## Architecture

```
alam/
  api/            FastAPI routers. Thin. No business logic.
  domain/         Pure functions. No I/O. See rule 3.
  services/       Orchestration across domain + persistence + ai.
  ai/
    providers/    LLM / embedding / STT Protocols + implementations + fakes.
    prompts/      Versioned prompt templates.
    extraction/   Transcript -> typed memories.
    retrieval/    (M3)
  media/
    base.py       MediaProvider Protocol.
    books/        The one implementation.
  persistence/    SQLAlchemy models, repositories, Alembic migrations.
  jobs/           Queue, worker loop, handlers.
  eval/           Evaluation harness. (M3)
  config/         Typed settings.
```

Dependency direction is strictly inward: `api` → `services` → `domain`.
`domain` imports nothing from the layers above it.

The Next.js frontend (`app/`, `lib/`, `proxy.ts`, `next.config.ts`) lives
at the repo root alongside this package, not nested under it — one Vercel
project serves both (ADR-0018). Its own page paths (`/library`, `/profile`,
`/recommended`, ...) are deliberately distinct from every router prefix
above; see ADR-0018 before adding either a new API router or a new
top-level frontend route.

---

## Conventions

- Python 3.12+, `uv` for dependency management.
- `ruff` for lint and format. `mypy --strict` on `domain/`, standard elsewhere.
- SQLAlchemy 2.0 style, fully typed. Alembic for every schema change; never
  edit a migration that has been applied.
- Pydantic v2 for all boundary types. `pydantic-settings` for config.
- UUIDv7 primary keys.
- All timestamps `TIMESTAMPTZ`, stored UTC.
- Tests use `pytest`. Any test that would touch the network is wrong — use the
  fake providers.
- Conventional commits.

---

## Working style

- Small, reviewable commits. One concern per commit.
- Write the test alongside the code, not after.
- When a task is ambiguous, ask rather than guessing at product intent.
- When you finish a task, state what you did NOT do that a reader might assume
  you did.
- Do not add dependencies without saying why in the commit message.

---

## Reference

- `docs/adr/` — architecture decision records. Read before schema changes.
- `docs/milestones.md` — milestone definitions of done.
