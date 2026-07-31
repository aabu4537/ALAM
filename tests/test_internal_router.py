"""Auth on the drain endpoint. No database — these never reach the queue."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from alam.api.main import create_app
from alam.config.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

DRAIN = "/internal/jobs/drain"
SECRET = "test-drain-secret"


@pytest.fixture
def secured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALAM_DRAIN_SECRET", SECRET)
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def test_unconfigured_secret_refuses_rather_than_opens(client: TestClient) -> None:
    """An unset environment variable must fail closed.

    The opposite default would leave a public endpoint that spins the queue for
    anyone who finds it — on a metered free tier, a billing problem as well as
    a correctness one.
    """
    response = client.post(DRAIN)

    assert response.status_code == 503


def test_missing_credentials_are_rejected(secured_client: TestClient) -> None:
    assert secured_client.post(DRAIN).status_code == 401


def test_wrong_secret_is_rejected(secured_client: TestClient) -> None:
    response = secured_client.post(DRAIN, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_non_bearer_scheme_is_rejected(secured_client: TestClient) -> None:
    response = secured_client.post(DRAIN, headers={"Authorization": f"Basic {SECRET}"})

    assert response.status_code == 401


def test_the_secret_is_never_echoed(secured_client: TestClient) -> None:
    response = secured_client.post(DRAIN, headers={"Authorization": "Bearer wrong"})

    assert SECRET not in response.text


def test_health_is_still_reachable_without_credentials(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
