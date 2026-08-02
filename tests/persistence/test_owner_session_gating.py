"""End-to-end: owner-scoped routes actually require a real session (M7
session 2, ADR-0017) — not just that the dependency is wired in
structurally (`tests/test_owner_session_coverage.py`), but that a real
`POST /auth/login` call is what it takes to pass. Builds its own client
without the `require_owner_session` no-op override every other DB test
gets from `tests/persistence/conftest.py`'s `client` fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from alam.api.main import create_app
from alam.config.settings import get_settings
from alam.persistence.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def real_auth_client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALAM_OWNER_PASSWORD", PASSWORD)
    get_settings.cache_clear()

    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


class TestOwnerSessionGating:
    def test_recommendations_401s_with_no_cookie(self, real_auth_client: TestClient) -> None:
        response = real_auth_client.get("/recommendations")

        assert response.status_code == 401

    def test_recommendations_200s_after_a_real_login(self, real_auth_client: TestClient) -> None:
        login = real_auth_client.post("/auth/login", json={"password": PASSWORD})
        assert login.status_code == 204

        response = real_auth_client.get("/recommendations")

        assert response.status_code == 200

    def test_a_wrong_password_never_grants_access(self, real_auth_client: TestClient) -> None:
        login = real_auth_client.post("/auth/login", json={"password": "wrong"})
        assert login.status_code == 401

        response = real_auth_client.get("/recommendations")

        assert response.status_code == 401

    def test_logout_revokes_access_immediately(self, real_auth_client: TestClient) -> None:
        real_auth_client.post("/auth/login", json={"password": PASSWORD})
        assert real_auth_client.get("/recommendations").status_code == 200

        real_auth_client.post("/auth/logout")

        assert real_auth_client.get("/recommendations").status_code == 401

    def test_preferences_taste_drift_is_gated_too(self, real_auth_client: TestClient) -> None:
        """Confirms the gate is applied router-wide, not just to the one
        route exercised above — a second router entirely."""
        response = real_auth_client.get("/preferences/taste-drift")

        assert response.status_code == 401

        real_auth_client.post("/auth/login", json={"password": PASSWORD})

        assert real_auth_client.get("/preferences/taste-drift").status_code == 200

    def test_demo_books_stays_public_even_while_gating_is_active(
        self, real_auth_client: TestClient
    ) -> None:
        """The demo endpoint must never require a session — it's the one
        surface meant to stay reachable by anyone (ADR-0005)."""
        response = real_auth_client.get("/demo/books")

        assert response.status_code == 200
