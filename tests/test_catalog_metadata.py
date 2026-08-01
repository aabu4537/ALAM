"""Pure reads over ``attributes["catalog"]`` (M6 session 4). No database —
plain dicts in and out."""

from __future__ import annotations

from typing import Any

from alam.domain.catalog_metadata import catalog_entry, has_catalog_content


class TestCatalogEntry:
    def test_missing_key_is_none(self) -> None:
        assert catalog_entry({}) is None

    def test_non_dict_value_is_none(self) -> None:
        assert catalog_entry({"catalog": "not a dict"}) is None

    def test_present_dict_is_returned(self) -> None:
        entry = {"blurb": "A tale.", "subjects": ["fiction"], "series": None}
        assert catalog_entry({"catalog": entry}) == entry


class TestHasCatalogContent:
    def test_never_fetched_is_false(self) -> None:
        assert has_catalog_content({}) is False

    def test_fetched_and_empty_is_false(self) -> None:
        """A definite "checked, found nothing" result — not the same as
        never having checked, but still nothing to reference."""
        attributes: dict[str, Any] = {"catalog": {"blurb": None, "subjects": [], "series": None}}
        assert has_catalog_content(attributes) is False

    def test_a_blurb_alone_is_true(self) -> None:
        attributes: dict[str, Any] = {
            "catalog": {"blurb": "A tale.", "subjects": [], "series": None}
        }
        assert has_catalog_content(attributes) is True

    def test_subjects_alone_is_true(self) -> None:
        attributes = {"catalog": {"blurb": None, "subjects": ["fiction"], "series": None}}
        assert has_catalog_content(attributes) is True
