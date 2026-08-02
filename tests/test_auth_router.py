"""POST /auth/login and /auth/logout (M7 session 2, ADR-0017). No database —
issuing/verifying a session token never touches it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from alam.api.main import create_app
from alam.auth.tokens import COOKIE_NAME
from alam.config.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def owner_password_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALAM_OWNER_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def test_login_unconfigured_password_refuses_rather_than_opens(client: TestClient) -> None:
    """An unset environment variable must fail closed — the same reasoning
    every other secret-gated endpoint in this codebase already applies."""
    response = client.post("/auth/login", json={"password": "anything"})

    assert response.status_code == 503


def test_wrong_password_is_rejected(owner_password_configured: TestClient) -> None:
    response = owner_password_configured.post("/auth/login", json={"password": "wrong"})

    assert response.status_code == 401


def test_correct_password_sets_a_cookie(owner_password_configured: TestClient) -> None:
    response = owner_password_configured.post("/auth/login", json={"password": PASSWORD})

    assert response.status_code == 204
    assert COOKIE_NAME in response.cookies


def test_the_cookie_is_httponly_and_samesite_lax(owner_password_configured: TestClient) -> None:
    response = owner_password_configured.post(
        "/auth/login", json={"password": PASSWORD}, follow_redirects=False
    )

    set_cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie_header
    assert "samesite=lax" in set_cookie_header.lower()


def test_the_password_is_never_echoed(owner_password_configured: TestClient) -> None:
    response = owner_password_configured.post("/auth/login", json={"password": "wrong"})

    assert PASSWORD not in response.text


def test_logout_clears_the_cookie(owner_password_configured: TestClient) -> None:
    owner_password_configured.post("/auth/login", json={"password": PASSWORD})

    response = owner_password_configured.post("/auth/logout")

    assert response.status_code == 204
    set_cookie_header = response.headers["set-cookie"]
    assert f'{COOKIE_NAME}=""' in set_cookie_header or f"{COOKIE_NAME}=" in set_cookie_header


def test_logout_with_no_prior_session_is_still_a_no_op_success(client: TestClient) -> None:
    response = client.post("/auth/logout")

    assert response.status_code == 204
