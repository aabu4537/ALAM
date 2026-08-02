# ADR-0017: Owner authentication — shared password, signed cookie

**Status:** Accepted
**Date:** 2026-08-02

## Context

M7's definition of done names "Frontend" as one of three items
(`docs/milestones.md`). Starting that session surfaced two findings that
had to be resolved first, not guessed at:

**Demo mode has almost nothing to show.** `GET /demo/books` is the only
endpoint reachable without resolving `UserRepository.get_owner()`, and it
returns a bare library list — title, author, rating, shelf, chapter
count. Every route that demonstrates what ALAM actually does (journey
summaries, recommendations, briefings, predictions, taste-drift) resolves
through `get_owner()`, which explicitly excludes the demo persona.

**Nothing gates the owner-scoped routes.** `books.py`, `captures.py`,
`preferences.py`, `recommendations.py`, and `imports.py` are reachable by
anyone who finds the URL. This was never a problem in practice — nothing
but `curl` and the test suite has ever called them — but a frontend
pointed at them is a browser anyone could reach, on a URL that's already
public (ADR-0005: "the evaluator... will not sign in," which describes
the *demo* surface, not an assumption that the owner's own routes were
ever protected).

Put to the user directly: build the frontend against the owner-scoped
routes — where the actual product is — with a lightweight auth gate added
first, rather than building a public demo-only frontend around what's
currently a bare book list, or widening demo mode's feature set before
any frontend exists to consume it. Confirmed as the recommended option,
not a default guess.

## Decision

### Shared password, not a full accounts system

CLAUDE.md is explicit: ALAM is "a single-user personal system," "not a
SaaS product." A real accounts system (multiple users, password reset
flows, per-user roles) would be building for a scale this project
explicitly declines to target. One password, configured once
(`ALAM_OWNER_PASSWORD`), is proportionate — the same reasoning
`drain_secret`/`demo_seed_secret` already establish for "a bearer secret
gates this," adapted here for a browser session instead of a
server-to-server call.

### A stdlib-only signed cookie, no new dependency

`alam/auth/tokens.py` — pure functions, no I/O, no dependency added:

```python
def issue_token(*, secret: bytes, now: dt.datetime, ttl: dt.timedelta) -> str:
    """`{expiry_unix_ts}.{hex_hmac_sha256}`"""


def verify_token(token: str, *, secret: bytes, now: dt.datetime) -> bool:
    """Constant-time signature comparison + expiry check. Malformed input
    is invalid, never an exception."""
```

The expiry is *signed*, not encrypted — there is nothing secret inside
the token, only something that must not be forged or silently extended.
`secrets.compare_digest` is the same constant-time-comparison idiom
`api/routers/internal.py`'s `require_drain_secret` already uses for a
bearer secret. `owner_password` doubles as the HMAC signing key — one
secret to configure, not two; an HMAC key only needs to be secret, not
independently random, so reusing the password this way costs nothing
cryptographically. A JWT library was considered and rejected: the token
this needs (an expiry, signed) is small enough to get right from the
stdlib, and CLAUDE.md's convention is not to add a dependency without
saying why — there was nothing to say.

`session_ttl_days` defaults to 30. Long-lived on purpose: this is Alam's
own personal app, not a banking session, and there is no accounts system
to revoke one compromised session from short of rotating the password
itself.

### `SameSite=Lax` is the CSRF answer, not a token scheme

The cookie is `HttpOnly` (inaccessible to any script, mitigating XSS
token theft), `Secure` outside `env=local` (never sent over plain HTTP in
a real deployment), and `SameSite=Lax`. That last flag is the chosen CSRF
mitigation in full — no separate CSRF token, no double-submit cookie
pattern. Proportionate to the actual threat model: a single-owner
personal app with no legitimate third-party origin that would ever need
to POST here. A full CSRF scheme defends against a threat this app
doesn't have; stated here explicitly so it reads as a decision, not an
oversight.

### Router-level enforcement, structurally checked

`require_owner_session` (`api/dependencies.py`) is applied via
`dependencies=[Depends(require_owner_session)]` on the `APIRouter(...)`
construction for `books`, `captures`, `preferences`, `recommendations`,
and `imports` — every route in each of those files is owner-only today,
so gating at the router avoids touching every individual route signature,
and a new route added to any of those files inherits the gate for free.
`internal.py` keeps its own, separate secret scheme (a different
audience — cron/server callers, not a browser session); `demo.py` and
`health.py` stay open by design.

`tests/test_owner_session_coverage.py` mirrors
`tests/test_reader_context_coverage.py`'s exact shape — the same file
that already caught two real spoiler-containment gaps (`/structure`,
`/predictions`) by enumerating every registered route rather than
trusting memory (ADR-0002 amendment). Every route either depends on
`require_owner_session` or appears in an explicit, reasoned `EXEMPTIONS`
list; a future owner-scoped route that forgets the dependency fails this
test, not a future audit.

### Not a milestone item on its own — a prerequisite this session found

`docs/milestones.md`'s M7 "Frontend" bullet doesn't mention auth; it
implicitly assumed the owner-scoped API was already safe to point a
browser at. It wasn't. This ADR — and the session that produced it — exist
because building the frontend surfaced that gap, the same way M6 session
2's design pass surfaced the groundedness gap in the original
recommendations sketch (ADR-0014). Recorded here rather than folded
silently into the frontend session so the reasoning survives independent
of whichever session actually consumes it.

## Consequences

**Positive.** The owner-scoped API — where the real product lives — is no
longer reachable by anyone who finds the URL. No new dependency. The
coverage-test pattern means this can't silently regress the way the two
`ReaderContext` gaps did before that test existed.

**Negative.** One password is a real single point of failure — anyone who
obtains it has full access, and there's no per-session revocation short
of rotating it (which invalidates every session at once, not just one).
Acceptable for a single-owner personal system; would not be for anything
with more than one real user. No rate-limiting on `POST /auth/login` —
a brute-force attempt against a long, random password is impractical, but
this is worth revisiting if the password is ever chosen weakly. `env=local`
runs without `Secure` on the cookie by design (so local `http://` testing
works), which means a locally running instance must never be reachable
over a shared, untrusted network.

## Alternatives considered

**A full accounts system (email/password, hashed with bcrypt/argon2, a
`users` auth table).** Rejected — over-building for a system with exactly
one real user, and CLAUDE.md says so directly.

**A JWT library (e.g. `python-jose`, `pyjwt`).** Rejected — the token
shape needed (an expiry, signed, nothing else) is small enough to
implement correctly from the stdlib, and every other secret check in this
codebase already uses `hmac`/`secrets` directly rather than pulling in a
token library for a narrower need than JWT's full feature set (multiple
claim types, algorithm negotiation, key rotation) actually calls for.

**Widen demo mode instead, and build a public-only frontend first.**
Considered as the plan's third option. Rejected for this session — it's
backend work with its own real design surface (which artifacts get
precomputed for the demo persona, whether they need to be regenerated as
the seed generator changes) that doesn't need to block starting on the
real product's frontend, and doesn't remove the eventual need for owner
auth once the real capture/synthesis flow is built regardless.
