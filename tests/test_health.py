from __future__ import annotations

from typing import TYPE_CHECKING

from alam.api.middleware import TRACE_HEADER

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_health_does_not_require_a_database(client: TestClient) -> None:
    """The liveness endpoint must not depend on Postgres. See routers/health.py."""
    response = client.get("/health")

    assert response.status_code == 200


def test_response_carries_a_trace_id(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers.get(TRACE_HEADER)


def test_inbound_trace_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health", headers={TRACE_HEADER: "abc123"})

    assert response.headers[TRACE_HEADER] == "abc123"


def test_trace_ids_differ_across_requests(client: TestClient) -> None:
    first = client.get("/health").headers[TRACE_HEADER]
    second = client.get("/health").headers[TRACE_HEADER]

    assert first != second
