"""Router-level checks. `/epub/preview` never touches the database, so its
happy path is tested here too, not just the failure path — unlike the
Goodreads import router, this one has no DB dependency to route around.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.epub_builder import build_epub

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

PREVIEW = "/books/epub/preview"


def test_empty_body_is_rejected(client: TestClient) -> None:
    response = client.post(PREVIEW, content=b"")

    assert response.status_code == 400


def test_not_a_zip_is_rejected(client: TestClient) -> None:
    response = client.post(PREVIEW, content=b"not an epub")

    assert response.status_code == 400
    assert "not a valid EPUB" in response.json()["detail"]


def test_a_real_epub_previews_without_touching_the_database(client: TestClient) -> None:
    response = client.post(PREVIEW, content=build_epub(title="Dune", author="Frank Herbert"))

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Dune"
    assert body["author"] == "Frank Herbert"
    assert [u["ordinal"] for u in body["units"]] == [1, 2]
    assert body["units"][0]["label"] == "Chapter One"
