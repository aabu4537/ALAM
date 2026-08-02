"""Enforces ADR-0017's invariant: every route that reads or writes the
owner's real data passes through `require_owner_session`, applied at the
router level — never left to be remembered route by route.

Mirrors `tests/test_reader_context_coverage.py`'s exact shape (the same
file that already caught two real spoiler-containment gaps by enumerating
routes rather than trusting memory, before the M6 audit found them).

Every route not wired to the dependency must appear in `EXEMPTIONS` with a
reason — enumerated explicitly, not filtered by convention (a path
prefix, a tag), since the reason a route is exempt is never mechanical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.api.dependencies import require_owner_session
from alam.api.main import create_app

if TYPE_CHECKING:
    from collections.abc import Callable

EXEMPTIONS: dict[tuple[str, str], str] = {
    ("GET", "/health"): "no owner data — an ops liveness check",
    ("POST", "/auth/login"): "issues the session itself — can't require one to get one",
    ("POST", "/auth/logout"): "clears the session — must work even with an invalid/expired one",
    ("GET", "/demo/books"): (
        "public by design (ADR-0005) — the seeded demo persona's library, "
        "never the owner's real data (CLAUDE.md rule 9)"
    ),
    ("POST", "/internal/jobs/drain"): (
        "internal, gated by its own separate drain_secret (ADR-0007) — a "
        "different audience (cron/server callers) than a browser session"
    ),
    ("POST", "/internal/demo/seed"): (
        "internal, gated by its own separate demo_seed_secret — writes "
        "fixed demo data, not owner data"
    ),
    ("POST", "/internal/embeddings/backfill"): (
        "internal, gated by drain_secret — same separate-audience reasoning as drain"
    ),
    ("POST", "/internal/preferences/consolidate"): (
        "internal, gated by drain_secret — same separate-audience reasoning as drain"
    ),
    ("POST", "/internal/catalog/backfill"): (
        "internal, gated by drain_secret — same separate-audience reasoning as drain"
    ),
    ("GET", "/internal/costs"): (
        "internal, gated by drain_secret — same separate-audience reasoning as drain"
    ),
}


def _registered_routes() -> list[tuple[str, str, list[Callable[..., object]]]]:
    """``(method, path, dependency_callables)`` for every route FastAPI has
    actually registered — read off ``app.routes`` rather than the
    individual router modules, so a route added and never wired into
    ``create_app`` (and therefore never reachable) can't silently satisfy
    this test. Same helper shape as
    ``tests/test_reader_context_coverage.py``."""
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


def test_every_route_either_requires_an_owner_session_or_is_an_explicit_exemption() -> None:
    routes = _registered_routes()
    assert routes, "no routes discovered — the introspection helper itself is broken"

    unaccounted = [
        (method, path)
        for method, path, dependencies in routes
        if require_owner_session not in dependencies and (method, path) not in EXEMPTIONS
    ]
    assert not unaccounted, (
        f"route(s) {unaccounted} neither require an owner session nor appear in "
        "EXEMPTIONS — add the dependency, or add an exemption with a reason"
    )


def test_no_stale_exemptions_for_routes_that_no_longer_exist() -> None:
    registered = {(method, path) for method, path, _ in _registered_routes()}
    stale = [key for key in EXEMPTIONS if key not in registered]
    assert not stale, f"exemption(s) {stale} reference routes that no longer exist"


def test_gated_routes_are_not_also_listed_as_exemptions() -> None:
    routes = _registered_routes()
    covered = {
        (method, path)
        for method, path, dependencies in routes
        if require_owner_session in dependencies
    }
    overlap = covered & EXEMPTIONS.keys()
    assert not overlap, f"route(s) {overlap} both require an owner session and are exempted"
