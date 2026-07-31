"""Vercel entrypoint.

Vercel builds a Python app into a single function resolved from this file, so
this exists only to expose the ASGI app the rest of the codebase already
builds. No logic belongs here — if something needs doing at startup, it belongs
in ``create_app``'s lifespan where local runs and tests exercise it too.

``maxDuration`` in vercel.json is 60s, comfortably above the 25s drain budget
and comfortably below Hobby's 300s ceiling with Fluid Compute. The gap on both
sides is deliberate: a drain returns on its own budget rather than being killed,
and a slow request has room before the platform intervenes.
"""

from alam.api.main import app

__all__ = ["app"]
