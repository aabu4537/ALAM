# M0 kickoff

Paste the prompt below into Claude Code as the first message in a fresh repo
that already contains `CLAUDE.md`, `docs/adr/`, and `docs/milestones.md`.

Do not paste the whole M0 definition of done at once. The queue is the only hard
part; everything else is scaffolding, and mixing them means the interesting code
gets rushed.

---

## Session 1 — scaffolding

> Read CLAUDE.md and docs/milestones.md before doing anything.
>
> We are in M0. Set up the project skeleton only — no job queue yet, no
> providers yet.
>
> Create the package layout described in CLAUDE.md with empty `__init__.py`
> files, a `pyproject.toml` using uv with FastAPI, SQLAlchemy 2.0, Alembic,
> psycopg, pydantic-settings, pytest, ruff, and mypy, a `docker-compose.yml`
> with Postgres 16 and pgvector plus the app container, typed settings in
> `config/`, a `.env.example`, a FastAPI app with `GET /health`, and a GitHub
> Actions workflow running ruff, mypy, and pytest.
>
> Then stop and show me the tree before writing any migrations.

## Session 2 — schema

> We are still in M0. Read ADR-0003 and ADR-0004 first.
>
> Write the first Alembic migration: enable the `vector` extension, then create
> `users`, `media_items`, and `media_structure_units` exactly as the ADRs
> describe. UUIDv7 primary keys, TIMESTAMPTZ everywhere.
>
> Add the SQLAlchemy models and a repository for each. Nothing else — no
> memories table, no chunks, those are later milestones.

## Session 3 — job queue

> We are still in M0. This is the only non-trivial part of the milestone, so go
> slowly.
>
> Build the Postgres job queue: a `jobs` table, `enqueue()`, and a worker loop
> claiming work with `SELECT ... FOR UPDATE SKIP LOCKED`. Retry with exponential
> backoff, a max attempt count, and a `last_error` column. One no-op handler.
>
> Write the concurrency test first: two workers running against a queue of N
> jobs, asserting every job is claimed exactly once. I want to see that test
> fail before the implementation exists.
>
> No Celery, no Redis. See CLAUDE.md rule 5.

## Session 4 — providers

> We are still in M0. Define Protocols in `ai/providers/` for the LLM,
> embedding, and speech-to-text interfaces, plus a fake implementation of each.
>
> Fakes only. No real API clients, no keys, no network. The point is that every
> later milestone can be tested offline.
>
> Keep the interfaces narrow — we can widen them when a real caller needs more.

## Session 5 — deploy

> We are still in M0. Deploy: web service and worker on Render (separate
> services, same repo), Postgres on Supabase with pgvector enabled.
>
> I want the health endpoint responding on the real URL and the worker running
> and logging its poll loop. Nothing else.
>
> Do not use a free tier that spins down — see ADR-0005.

---

## Discipline notes

**Start every session by naming the milestone.** The design docs in this repo
describe the whole system; a coding agent reading them will find M3 retrieval
work genuinely tempting and it will look like progress.

**Update `CLAUDE.md`'s "Current milestone" section when you move.** It is the
only line in the file that goes stale.

**When a session ends, ask what it did *not* do.** The gap between what you
assume was built and what was built is where the bugs live.
