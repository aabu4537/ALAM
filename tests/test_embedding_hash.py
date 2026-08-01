from __future__ import annotations

from alam.domain.embedding_hash import embedding_content_hash


class TestEmbeddingContentHash:
    def test_same_inputs_produce_the_same_hash(self) -> None:
        a = embedding_content_hash(
            content="The narrator is unreliable.",
            embedding_model="fake-embedding-v1",
            embedding_version="1",
        )
        b = embedding_content_hash(
            content="The narrator is unreliable.",
            embedding_model="fake-embedding-v1",
            embedding_version="1",
        )

        assert a == b

    def test_different_content_produces_a_different_hash(self) -> None:
        a = embedding_content_hash(
            content="one", embedding_model="fake-embedding-v1", embedding_version="1"
        )
        b = embedding_content_hash(
            content="two", embedding_model="fake-embedding-v1", embedding_version="1"
        )

        assert a != b

    def test_different_model_produces_a_different_hash(self) -> None:
        """A model swap must not be mistaken for already-embedded content."""
        a = embedding_content_hash(content="x", embedding_model="model-a", embedding_version="1")
        b = embedding_content_hash(content="x", embedding_model="model-b", embedding_version="1")

        assert a != b

    def test_different_version_produces_a_different_hash(self) -> None:
        a = embedding_content_hash(content="x", embedding_model="model-a", embedding_version="1")
        b = embedding_content_hash(content="x", embedding_model="model-a", embedding_version="2")

        assert a != b

    def test_a_field_boundary_shift_does_not_collide(self) -> None:
        """Without a separator, ("ab", "c") and ("a", "bc") under the same
        third field would hash identically."""
        a = embedding_content_hash(content="ab", embedding_model="c", embedding_version="v")
        b = embedding_content_hash(content="a", embedding_model="bc", embedding_version="v")

        assert a != b

    def test_output_is_a_hex_sha256_digest(self) -> None:
        result = embedding_content_hash(content="x", embedding_model="m", embedding_version="1")

        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)
