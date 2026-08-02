"""``GET /internal/costs`` (M7 session 1): the response body shape against
real seeded ``llm_calls`` rows. Auth itself is covered by
``tests/test_internal_router.py`` (no database there); this file's `client`
fixture (``tests/persistence/conftest.py``) is DB-backed but doesn't
configure a drain secret by default, so each test here sets one directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.config.settings import get_settings
from alam.persistence.repositories.llm_calls import LLMCallRepository

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

_SECRET = "test-costs-secret"


@pytest.fixture
def _drain_secret_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALAM_DRAIN_SECRET", _SECRET)
    get_settings.cache_clear()


def test_an_empty_llm_calls_table_returns_a_zeroed_body(
    client: TestClient, _drain_secret_configured: None
) -> None:
    response = client.get("/internal/costs", headers={"Authorization": f"Bearer {_SECRET}"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 0
    assert body["total_cost_usd"] == 0.0
    assert body["by_model"] == []
    assert body["by_call_site"] == []
    assert body["recent_calls"] == []


def test_seeded_calls_produce_the_expected_shape(
    session: Session, client: TestClient, _drain_secret_configured: None
) -> None:
    LLMCallRepository(session).create(
        call_site="alam.services.recommendations._generate",
        provider="anthropic",
        prompt_version_id="v1",
        model="claude-sonnet-4-5-20250929",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        latency_ms=250.0,
        job_id=None,
    )

    response = client.get("/internal/costs", headers={"Authorization": f"Bearer {_SECRET}"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 1
    assert body["total_cost_usd"] == pytest.approx(18.00)
    assert len(body["by_model"]) == 1
    assert body["by_model"][0]["model"] == "claude-sonnet-4-5-20250929"
    assert body["by_model"][0]["cost_usd"] == pytest.approx(18.00)
    assert len(body["recent_calls"]) == 1
    assert body["recent_calls"][0]["cost_usd"] == pytest.approx(18.00)
