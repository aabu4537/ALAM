"""Auth on the drain and demo-seed endpoints. No database — a rejected request
never reaches either the queue or the demo seeding logic."""

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

DEMO_SEED = "/internal/demo/seed"
DEMO_SEED_SECRET = "test-demo-seed-secret"

EMBEDDING_BACKFILL = "/internal/embeddings/backfill"


@pytest.fixture
def secured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALAM_DRAIN_SECRET", SECRET)
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture
def demo_seed_secured_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALAM_DEMO_SEED_SECRET", DEMO_SEED_SECRET)
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture
def both_secrets_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALAM_DRAIN_SECRET", SECRET)
    monkeypatch.setenv("ALAM_DEMO_SEED_SECRET", DEMO_SEED_SECRET)
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


def test_demo_seed_unconfigured_secret_refuses_rather_than_opens(client: TestClient) -> None:
    """A write endpoint with an unset secret must fail closed, same as drain —
    a spam vector even though the data it writes is fixed and harmless."""
    response = client.post(DEMO_SEED)

    assert response.status_code == 503


def test_demo_seed_missing_credentials_are_rejected(demo_seed_secured_client: TestClient) -> None:
    assert demo_seed_secured_client.post(DEMO_SEED).status_code == 401


def test_demo_seed_wrong_secret_is_rejected(demo_seed_secured_client: TestClient) -> None:
    response = demo_seed_secured_client.post(DEMO_SEED, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_demo_seed_drain_secret_does_not_also_work(demo_seed_secured_client: TestClient) -> None:
    """The two endpoints deliberately use separate secrets (different blast
    radii) — one leaking must not imply the other is exposed."""
    response = demo_seed_secured_client.post(
        DEMO_SEED, headers={"Authorization": f"Bearer {SECRET}"}
    )

    assert response.status_code == 401


def test_demo_seed_secret_is_never_echoed(demo_seed_secured_client: TestClient) -> None:
    response = demo_seed_secured_client.post(DEMO_SEED, headers={"Authorization": "Bearer wrong"})

    assert DEMO_SEED_SECRET not in response.text


def test_embedding_backfill_unconfigured_secret_refuses_rather_than_opens(
    client: TestClient,
) -> None:
    """Reuses require_drain_secret, so an unset secret fails closed the same
    way the drain endpoint does."""
    response = client.post(EMBEDDING_BACKFILL)

    assert response.status_code == 503


def test_embedding_backfill_missing_credentials_are_rejected(
    secured_client: TestClient,
) -> None:
    assert secured_client.post(EMBEDDING_BACKFILL).status_code == 401


def test_embedding_backfill_wrong_secret_is_rejected(secured_client: TestClient) -> None:
    response = secured_client.post(EMBEDDING_BACKFILL, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_embedding_backfill_demo_seed_secret_does_not_also_work(
    both_secrets_client: TestClient,
) -> None:
    """The embeddings backfill endpoint deliberately shares drain_secret, not
    demo_seed_secret. With both configured, the demo-seed token must still be
    rejected here — only the drain secret should authenticate this endpoint.
    Accepted-credentials behaviour needs a real database, which this
    TestClient's app doesn't have wired up — same reason drain_jobs and
    seed_demo have no 200-path test here either; embed_memories_backfill
    itself is exercised directly against the `session` fixture in
    tests/persistence/test_embedding_backfill.py."""
    response = both_secrets_client.post(
        EMBEDDING_BACKFILL, headers={"Authorization": f"Bearer {DEMO_SEED_SECRET}"}
    )

    assert response.status_code == 401
