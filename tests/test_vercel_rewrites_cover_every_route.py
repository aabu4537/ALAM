"""Enforces the M7 session 3 deployment-topology invariant: once Next.js
becomes the project's Vercel framework, `vercel.json`'s old catch-all
rewrite (`"/(.*)" -> "/api/index"`) is gone — every backend path now needs
its own explicit rewrite entry, or Vercel's framework routing swallows it
and the route 404s in production while every test here still passes.

Same enumerate-don't-trust-memory idiom as
`tests/test_reader_context_coverage.py` and
`tests/test_owner_session_coverage.py`: a new router registered and
forgotten in `vercel.json` fails this test, not a production 404.
"""

from __future__ import annotations

import json
from pathlib import Path

from alam.api.main import create_app

_VERCEL_JSON = Path(__file__).resolve().parent.parent / "vercel.json"


def _registered_top_level_segments() -> set[str]:
    """The first path segment of every route FastAPI has actually
    registered, e.g. ``/books/{media_item_id}/captures`` -> ``books``."""
    app = create_app()
    segments: set[str] = set()
    for mount in app.routes:
        router = getattr(mount, "original_router", None)
        if router is None:
            continue
        for route in router.routes:
            path = getattr(route, "path", None)
            if not path:
                continue
            first = path.strip("/").split("/", 1)[0]
            if first:
                segments.add(first)
    return segments


def _rewritten_top_level_segments() -> set[str]:
    """The first path segment of every ``source`` in `vercel.json`'s
    rewrites — ``/books/:path*`` and ``/books`` both yield ``books``."""
    config = json.loads(_VERCEL_JSON.read_text())
    segments: set[str] = set()
    for rewrite in config["rewrites"]:
        source = rewrite["source"]
        first = source.strip("/").split("/", 1)[0]
        if first and first != "(.*)":
            segments.add(first)
    return segments


def test_every_registered_route_has_a_vercel_rewrite() -> None:
    registered = _registered_top_level_segments()
    assert registered, "no routes discovered — the introspection helper itself is broken"

    rewritten = _rewritten_top_level_segments()
    missing = registered - rewritten
    assert not missing, (
        f"path segment(s) {missing} are registered FastAPI routes with no matching "
        "vercel.json rewrite — they will 404 in production once Next.js owns "
        "unmatched routing"
    )


def test_no_stale_rewrites_for_segments_that_no_longer_exist() -> None:
    """A leftover rewrite for a removed router is harmless in production but
    is exactly the kind of drift this file exists to catch before it hides
    a real gap the next time a route is added."""
    stale = _rewritten_top_level_segments() - _registered_top_level_segments()
    assert not stale, f"vercel.json rewrite(s) for {stale} reference routes that no longer exist"
