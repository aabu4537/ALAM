"""Router-level checks that short-circuit before touching the database.

Everything past body validation needs a real Postgres and lives in
tests/persistence/test_goodreads_import.py against the `session` fixture,
following this project's existing split between DB-backed and DB-free tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

PREVIEW = "/imports/goodreads/preview"
COMMIT = "/imports/goodreads/commit"


def test_empty_body_is_rejected_before_any_db_access(client: TestClient) -> None:
    response = client.post(PREVIEW, content=b"")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_non_utf8_body_is_rejected(client: TestClient) -> None:
    response = client.post(PREVIEW, content=b"\xff\xfe\x00\x01")

    assert response.status_code == 400


def test_commit_also_rejects_an_empty_body(client: TestClient) -> None:
    response = client.post(COMMIT, content=b"")

    assert response.status_code == 400
