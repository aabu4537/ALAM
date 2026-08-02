"""Owner session login/logout (M7 session 2, ADR-0017).

Shared-password gate for a single-owner personal system — not a full
accounts system, just something that isn't wide open to the public
internet. `require_owner_session` (`api/dependencies.py`) is the other
half: this router issues the cookie, that dependency checks it on every
owner-scoped route.

`SameSite=Lax` is the chosen CSRF mitigation, not a separate CSRF token
scheme — proportionate to a single-owner app with no legitimate
third-party origin ever needing to POST here (ADR-0017).
"""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from alam.auth.tokens import COOKIE_NAME, issue_token, signing_key
from alam.config.settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(
    payload: LoginRequest, response: Response, settings: Settings = Depends(get_settings)
) -> None:
    """Refuses outright when no password is configured, same "unset means
    refuse, not open" idiom `internal.py`'s `require_drain_secret` already
    uses — an unset environment variable should fail closed, not leave
    every owner-scoped route reachable by whoever guesses an empty
    password check passes."""
    expected = settings.owner_password
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="owner login is not configured",
        )

    if not secrets.compare_digest(payload.password, expected.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password")

    ttl = dt.timedelta(days=settings.session_ttl_days)
    token = issue_token(secret=signing_key(expected), now=dt.datetime.now(dt.UTC), ttl=ttl)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=settings.env != "local",
        path="/",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    """Unconditional — clearing a cookie that was never set is a no-op,
    not an error worth distinguishing from clearing a real one."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
