"""Enforces the ADR-0002 amendment's invariant: every reader-facing route
that returns media-derived content passes through a ``ReaderContext``,
resolved server-side via ``api.dependencies.reader_context_dependency`` —
never a caller-suppliable ordinal.

This exists because the invariant was violated twice (``/structure`` since
M1, ``/predictions`` since M5) before anyone checked, and each was found by
manual audit rather than a failing test. A route that returns book content
and forgets the dependency must fail here, not wait for the next audit.

Every route not wired to the dependency must appear in ``EXEMPTIONS`` with a
reason — enumerated explicitly, not filtered by convention (a path prefix,
a tag), since the reason a route is exempt is never mechanical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.api.dependencies import reader_context_dependency
from alam.api.main import create_app

if TYPE_CHECKING:
    from collections.abc import Callable

# (method, path) -> why this route legitimately returns media-derived
# content, or no content at all, without a ReaderContext.
EXEMPTIONS: dict[tuple[str, str], str] = {
    ("GET", "/health"): "no media content — an ops liveness check",
    ("POST", "/internal/jobs/drain"): (
        "internal, secret-gated job-queue trigger (ADR-0007) — not reader-facing"
    ),
    ("POST", "/internal/demo/seed"): (
        "internal, secret-gated — writes fixed demo data, not a read of anyone's position"
    ),
    ("POST", "/internal/embeddings/backfill"): (
        "internal, secret-gated — enqueues jobs, returns no content"
    ),
    ("POST", "/internal/preferences/consolidate"): (
        "internal, secret-gated — enqueues jobs, returns no content"
    ),
    ("POST", "/internal/catalog/backfill"): (
        "internal, secret-gated — enqueues jobs, returns no content (M6 session 3)"
    ),
    ("POST", "/imports/goodreads/preview"): (
        "library metadata diff (ratings, shelves) — not ordinal-scoped book content"
    ),
    ("POST", "/imports/goodreads/commit"): (
        "applies the same metadata diff — not ordinal-scoped book content"
    ),
    ("POST", "/books/epub/preview"): (
        "parses an uploaded EPUB in memory, no database access at all"
    ),
    ("POST", "/books/epub/commit"): (
        "echoes the structure the caller just uploaded, always unverified at "
        "this point — nothing yet to scope to a reading position"
    ),
    ("GET", "/books/{media_item_id}/structure"): (
        "the verification read (ADR-0004 steps 2-4), gated separately: "
        "permitted only while structure_verified_at is null, refused once "
        "verified. GET .../chapters is the ReaderContext-scoped reading "
        "equivalent — this route is deliberately not that, by the ADR-0002 "
        "amendment's own design"
    ),
    ("PUT", "/books/{media_item_id}/structure"): (
        "echoes the result of the human's own verification correction — not "
        "an arbitrary read of existing position-relevant state"
    ),
    ("POST", "/books/{media_item_id}/captures"): (
        "creates a capture at the structure_unit_id the caller selects as "
        "the reading act itself (ADR-0004: progress is captured as part of "
        "the recording act) — not a read of existing content"
    ),
    ("GET", "/books/{media_item_id}/reading-sessions/active"): (
        "session metadata only (ordinal, progress, status) — no book content"
    ),
    ("POST", "/books/{media_item_id}/reading-sessions/{reading_session_id}/end"): (
        "echoes the session's own state after the caller's own end action"
    ),
    ("GET", "/demo/books"): (
        "demo library metadata (title, author, rating, chapter_count) — no "
        "plot or reflection content, and CLAUDE.md rule 9 already keeps this "
        "off the owner's real data"
    ),
    ("GET", "/preferences/taste-drift"): (
        "M4 preference facts are consolidated across books by design — not "
        "scoped to any single media_item_id or ordinal, so there is no "
        "ReaderContext to construct. Mitigated at the prompt level (write a "
        "general statement, not a memory restatement), not structurally"
    ),
    ("GET", "/recommendations"): (
        "M6 session 2 recommendations are library-wide by design, same as "
        "taste-drift above — not scoped to any single media_item_id or "
        "ordinal, so there is no ReaderContext to construct. Spoiler risk "
        "here isn't ordinal-shaped either: mitigated structurally by the "
        "response schema having no field an LLM-authored characterization "
        "of a candidate's content could occupy, not by ReaderContext "
        "(ADR-0014)"
    ),
    ("GET", "/books/{media_item_id}/briefing"): (
        "M6 session 4 briefings are pre-book by definition — the route "
        "refuses once an active ReadingSession exists, so there is never a "
        "reading position to construct a ReaderContext from. Spoiler risk "
        "is mitigated the same structural way recommendations are "
        "(ADR-0014/ADR-0015): the response schema has no field an "
        "LLM-authored characterization of the candidate's content could "
        "occupy — the teaser is always ALAM-composed from the candidate's "
        "own cached catalog entry, never LLM-cited"
    ),
}


def _registered_routes() -> list[tuple[str, str, list[Callable[..., object]]]]:
    """``(method, path, dependency_callables)`` for every route FastAPI has
    actually registered — read off ``app.routes`` rather than the
    individual router modules, so a route added and never wired into
    ``create_app`` (and therefore never reachable) can't silently satisfy
    this test."""
    app = create_app()
    routes: list[tuple[str, str, list[Callable[..., object]]]] = []
    for mount in app.routes:
        router = getattr(mount, "original_router", None)
        if router is None:
            continue
        for route in router.routes:
            methods = getattr(route, "methods", None)
            if not methods:
                continue
            [method] = [m for m in methods if m != "HEAD"] or methods
            dependencies = [dep.call for dep in route.dependant.dependencies]
            routes.append((method, route.path, dependencies))
    return routes


def test_every_route_either_uses_reader_context_or_is_an_explicit_exemption() -> None:
    routes = _registered_routes()
    assert routes, "no routes discovered — the introspection helper itself is broken"

    unaccounted = [
        (method, path)
        for method, path, dependencies in routes
        if reader_context_dependency not in dependencies and (method, path) not in EXEMPTIONS
    ]
    assert not unaccounted, (
        f"route(s) {unaccounted} neither use reader_context_dependency nor appear in "
        "EXEMPTIONS — add the dependency, or add an exemption with a reason"
    )


def test_no_stale_exemptions_for_routes_that_no_longer_exist() -> None:
    registered = {(method, path) for method, path, _ in _registered_routes()}
    stale = [key for key in EXEMPTIONS if key not in registered]
    assert not stale, f"exemption(s) {stale} reference routes that no longer exist"


def test_reader_context_routes_are_not_also_listed_as_exemptions() -> None:
    routes = _registered_routes()
    covered = {
        (method, path)
        for method, path, dependencies in routes
        if reader_context_dependency in dependencies
    }
    overlap = covered & EXEMPTIONS.keys()
    assert not overlap, f"route(s) {overlap} are both ReaderContext-scoped and exempted"
