"""Signed session tokens (M7 session 2, ADR-0017).

No I/O, no clock reads of its own (`now` is always passed in, never
`dt.datetime.now()` internally) — testable in milliseconds, same
discipline `domain/` modules follow even though this lives in its own
top-level package (see the package docstring for why).

Token shape: ``{expiry_unix_ts}.{hex_hmac_sha256}``. The expiry is
*signed*, not encrypted — there is nothing secret in it, only something
that must not be forged or silently extended. ``secrets.compare_digest``
for the signature check is the same constant-time-comparison idiom
``api/routers/internal.py``'s ``require_drain_secret`` already uses for a
bearer secret; a session token is the same kind of "must not be
forgeable" check applied to a value produced by this process instead of
one the caller already had.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt

    from pydantic import SecretStr

COOKIE_NAME = "alam_session"
"""Shared between `api/routers/auth.py` (sets/clears it) and
`api/dependencies.py`'s `require_owner_session` (reads it) — defined here
rather than duplicated in both, since it's a fact about the token this
module owns, not about either caller."""


def signing_key(owner_password: SecretStr) -> bytes:
    """The configured owner password doubles as the HMAC signing key —
    one secret to configure, not two. An HMAC key only needs to be
    secret, not independently random, so this is fine cryptographically."""
    return owner_password.get_secret_value().encode()


def _signature(payload: str, *, secret: bytes) -> str:
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def issue_token(*, secret: bytes, now: dt.datetime, ttl: dt.timedelta) -> str:
    """``now``/``ttl`` are parameters, not read internally, so the whole
    module stays a pure function of its inputs — the caller (``api/routers
    /auth.py``) owns the actual clock and the configured session length."""
    payload = str(int((now + ttl).timestamp()))
    return f"{payload}.{_signature(payload, secret=secret)}"


def verify_token(token: str, *, secret: bytes, now: dt.datetime) -> bool:
    """Malformed input is treated as invalid, never as an exception a
    caller has to handle — a corrupted or absent cookie is exactly as
    unauthenticated as one that was never set."""
    parts = token.split(".")
    if len(parts) != 2:
        return False
    payload, signature = parts
    if not payload.isdigit():
        return False
    if not secrets.compare_digest(signature, _signature(payload, secret=secret)):
        return False
    return now.timestamp() < int(payload)
