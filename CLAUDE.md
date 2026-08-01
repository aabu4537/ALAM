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

**M6 — Synthesis.** M0 through M5 are complete, plus two pieces of work done
ahead of M6 rather than as part of it: real (paid, $0-gated, and local)
providers with `llm_calls` instrumentation, and a `ReaderContext` hardening
pass that closed spoiler-containment gaps in `/structure` and `/predictions`
(ADR-0002 amendment, ADR-0012).

M6 was explicitly scoped down at its start, 2026-08-01, per
`docs/milestones/M6-open-questions.md`: no agent (`docs/milestones.md`'s
own invitation to reconsider rule 4 was declined directly, not by
default — see that rule below), `media/base.py` stays deferred, no
memory deletion/edit path. `content_chunks` / raw book text stays declined
per ADR-0010; M6 reads `media_items.attributes`, `memories`,
`preference_facts`, and `predictions` only.

Nothing outside the M6 definition of done in `docs/milestones.md` should be
implemented. If a task seems to require a later milestone's code, stop and say
so rather than building it.

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
- Frontend beyond a health page (M7)
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
