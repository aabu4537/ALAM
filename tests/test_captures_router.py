"""Router-level checks that short-circuit before touching the database.

Everything past body validation needs a real Postgres and lives in
tests/persistence/test_capture_pipeline.py, following this project's existing
split between DB-backed and DB-free tests.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

MEDIA_ITEM_ID = uuid.uuid4()
STRUCTURE_UNIT_ID = uuid.uuid4()


def _captures_url() -> str:
    return f"/books/{MEDIA_ITEM_ID}/captures?structure_unit_id={STRUCTURE_UNIT_ID}"


def test_empty_body_is_rejected_before_any_db_access(client: TestClient) -> None:
    response = client.post(_captures_url(), content=b"")

    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_missing_structure_unit_id_is_a_validation_error(client: TestClient) -> None:
    response = client.post(f"/books/{MEDIA_ITEM_ID}/captures", content=b"fake-audio")

    assert response.status_code == 422


def test_non_uuid_media_item_id_is_a_validation_error(client: TestClient) -> None:
    response = client.post(
        f"/books/not-a-uuid/captures?structure_unit_id={STRUCTURE_UNIT_ID}",
        content=b"fake-audio",
    )

    assert response.status_code == 422


def test_end_session_requires_a_known_status_value(client: TestClient) -> None:
    response = client.post(
        f"/books/{MEDIA_ITEM_ID}/reading-sessions/{uuid.uuid4()}/end?end_status=nope"
    )

    assert response.status_code == 422
