# ADR-0018: Frontend deployment topology and design system

**Status:** Accepted
**Date:** 2026-08-02

## Context

M7 session 3 builds the Next.js frontend `docs/milestones.md` names as an M7
item and ADR-0005 already committed to as the frontend framework. Two things
had to be decided before any page code, neither of them defaults:

1. **Where Next.js and the existing `api/index.py` (FastAPI, already
   deployed on Vercel — ADR-0005's implementation-status note) live
   relative to each other.**
2. **What the frontend actually looks like.** The user asked for a bold,
   distinctive interface and explicitly ruled out generic "AI slop"
   defaults (Inter/system fonts, purple-gradient SaaS chrome) before this
   session began.

## Decision — deployment topology

**One Vercel project.** Next.js becomes the project's framework at the
repo root, alongside the existing Python project files (not nested under
`web/` — Vercel's Root Directory setting is project-wide, so nesting the
Next app would hide `api/index.py` from the same build). `api/index.py`
is untouched and keeps serving the same FastAPI app at the same routes.

`vercel.json`'s old catch-all rewrite (`"/(.*)" -> "/api/index"`) is
replaced with one explicit rewrite per backend router prefix (`/health`,
`/auth/:path*`, `/books`, `/books/:path*`, `/demo/:path*`,
`/internal/:path*`, `/preferences/:path*`, `/recommendations`,
`/imports/:path*`). Everything else — every Next.js page — falls through
to the framework's own routing. `tests/test_vercel_rewrites_cover_every_route.py`
enforces this structurally: a new backend router added later and
forgotten in `vercel.json` fails a test rather than 404ing in production,
same idiom `tests/test_reader_context_coverage.py` and
`tests/test_owner_session_coverage.py` already established.

No FastAPI route path changed, so `/internal/jobs/drain` keeps resolving
exactly where Supabase's `pg_cron` already calls it (ADR-0007) — nothing
external breaks.

**Same origin means no auth redesign and no CORS.** ADR-0017's
`SameSite=Lax` session cookie keeps working exactly as built: browser
`fetch` calls to relative paths carry it automatically. Server Components
have no browser cookie jar, so `lib/server-api.ts`'s `apiFetch` forwards
the incoming request's `Cookie` header manually, and resolves the API's
base URL from `API_BASE_URL` (local dev), or the incoming request's own
host (production — same domain serves both).

Local dev runs the Next dev server and `uvicorn` as two separate
processes on two separate ports; `next.config.ts`'s `rewrites()` proxies
the same backend path-prefix list to `API_BASE_URL` (default
`http://localhost:8000`) so browser-initiated `fetch` calls during
`npm run dev` reach the API at all. This list is hand-kept in sync with
`vercel.json`'s — there's no way to share it as code across a JSON file
and a TS config, so both carry a comment pointing at the other.

### A real bug this surfaced: frontend and backend paths cannot share a first segment

The first cut of this design gave the frontend `/books/[id]` and
`/books/[id]/verify` pages — natural names, but they share `/books` with
the backend router. Verified locally against a deploy-shaped setup (the
Next dev server proxying through `next.config.ts`'s rewrites exactly the
way `vercel.json` will in production): both pages 404'd. `next.config.ts`
rewrites given as a plain array are applied "after checking the
filesystem... and before dynamic routes" (Next's own `rewrites.md`) — a
dynamic page route never gets a chance once a rewrite's source matches
first. `vercel.json`'s rewrites run at an even earlier, platform-level
layer with no `beforeFiles`/`afterFiles`/`fallback` ordering to lean on
at all, so reordering the rewrite wouldn't have been a safe fix even if
it had worked around the local symptom.

**Fix:** rename every frontend page whose first path segment collided
with a backend router prefix — `/books/[id]` → `/library/[id]`,
`/preferences` → `/profile`, `/recommendations` → `/recommended` — so no
pattern-matching ambiguity exists at all, regardless of exactly how any
given rewrite engine handles zero-or-more segment wildcards. Same
"structural unrepresentability over detection" principle ADR-0002 and
ADR-0014 already use for spoiler containment, applied to routing: the
fix is a URL namespace where the collision cannot occur, not a rule that
detects and avoids it. `/import` (frontend) and `/imports` (backend) were
already distinct strings and needed no change; `/login` and `/auth`
likewise never collided.

### Alternatives considered

**Two Vercel projects** (frontend and API as separate deployments,
frontend calling the API by full URL). Rejected: `*.vercel.app` is on the
Public Suffix List, so two projects are cross-site to each other for
`SameSite` purposes even under one Vercel account — ADR-0017's cookie
would stop being sent on cross-project fetches, forcing either a
`SameSite=None` rework (reopening the CSRF question ADR-0017 already
closed) or a custom shared subdomain setup neither ADR-0005 nor ADR-0017
anticipated. One project sidesteps this entirely.

**Moving FastAPI off Vercel** (Render/Fly, per ADR-0005's original,
never-implemented plan). Rejected: it already runs on Vercel in
production (ADR-0005's own implementation-status note); reversing that
now is a bigger, unrelated migration this session has no reason to force.

## Decision — design system: "the commonplace book"

ALAM's core loop is a private, voice-driven reading journal with a real,
stated guarantee (spoiler containment) most reading apps only gesture at.
The interface aims for a kept personal reading journal / library
annotation system, not SaaS dashboard chrome.

- **Typography.** Fraunces (display/headings) + Newsreader (body) +
  IBM Plex Mono (ordinals/timestamps, styled like library catalog
  stamps) via `next/font/google` — self-hosted at build time, no
  external font requests. No Inter, no system font stack.
- **Color.** Warm paper cream background, deep ink-navy text, one accent
  (wax-seal red) used sparingly; dark mode reads as aged leather, not
  slate-gray. Tokens live in `app/globals.css` as CSS custom properties,
  overridable by `:root[data-theme]` or `prefers-color-scheme`.
- **No component library, no Tailwind.** Plain CSS Modules per component.
  The few genuinely unusual choices here (torn-paper dividers, the
  wax-seal motif, the page-settle reveal) fight a utility-class or
  prebuilt-kit workflow more than they're helped by it, and this adds no
  runtime dependency beyond Next.js and its React peer deps.
- **The differentiator, made visual.** `app/components/SpoilerSeal.tsx`
  renders a literal wax-seal badge over content the API has declined to
  resolve yet (a pending, not-yet-due prediction) — never a client-side
  redaction of data that was fetched and then hidden. The frontend can't
  leak what it was never given; the seal only ever labels that absence.
- **Composition.** The book hub (`app/library/[id]/page.tsx`) uses an
  asymmetric two-column "book spread" on wide viewports — a main content
  column plus a narrower marginalia rail — divided by a torn-paper
  diagonal (`hub.module.css`'s `.spread::before`) instead of a hairline.
- **Motion.** One page-settle reveal on load (`.page-settle` in
  `globals.css`, `prefers-reduced-motion`-aware), not scattered
  micro-interactions.

### Not built this session

No public demo-mode UI (the user's earlier choice was owner-scoped +
auth, not demo-first — `GET /demo/books` stays backend-only, unconsumed
by any page). No drag-and-drop structure editor (`/library/[id]/verify` is
a plain editable table — a one-time-per-book flow doesn't justify more).
No full offline/background-sync PWA — `lib/captureQueue.ts` is an
IndexedDB retry queue for a failed capture upload, not a service worker.

## Consequences

**Positive.** No new deployment surface, no CORS, no auth rework. The
route-coverage-test pattern this codebase already leans on gets a third
instance, catching the same class of "forgot to wire it up" bug the
first two already caught for `ReaderContext` and `require_owner_session`.

**Negative.** `vercel.json` and `next.config.ts` must be updated together
by hand whenever a backend router's path prefix changes — a real
maintenance seam, mitigated but not eliminated by the coverage test
(it catches a forgotten `vercel.json` entry; it does not catch a
forgotten `next.config.ts` entry, since that file isn't Python-testable
the same way). A future session touching either should update both.
