"""
Tests for the vector store module (db/vectors.py).

These tests use a mock embedding service to avoid requiring the actual
sentence-transformers model. They DO require qdrant-client to be installed.
Tests are automatically skipped if qdrant-client is not available.
"""

from unittest.mock import patch

import pytest

import db
from db import core

# Skip entire module if qdrant-client is not installed
pytest.importorskip("qdrant_client", reason="qdrant-client not installed")


# Stable fake embeddings (768-dim like all-mpnet-base-v2)
def _fake_embed(text):
    """Deterministic fake embedding based on text hash."""
    import math

    # Bag-of-words embedding: each unique word maps to a stable
    # dimension via hash, producing high cosine similarity for
    # texts sharing words (unlike SHA-256 which destroys overlap).
    DIM = 768
    vec = [0.0] * DIM
    for word in text.lower().split():
        idx = hash(word) % DIM
        vec[idx] += 1.0
    # Normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def _fake_embed_batch(texts, **kwargs):
    return [_fake_embed(t) for t in texts]


@pytest.fixture
def vector_db(tmp_path):
    """Provide isolated SQLite + Qdrant vector store for tests."""
    knowledge = tmp_path / "knowledge.db"
    chat = tmp_path / "chat_history.db"
    vector_path = tmp_path / "vectors"

    with (
        patch.object(core, "KNOWLEDGE_DB", knowledge),
        patch.object(core, "CHAT_DB", chat),
        patch("db.core.KNOWLEDGE_DB", knowledge),
        patch("db.core.CHAT_DB", chat),
        patch("db.core._init_vector_store"),
        patch("config.VECTOR_STORE_PATH", vector_path),
        patch("config.EMBEDDING_MODEL", "test-model"),
        patch("config.SIMILARITY_THRESHOLD_DEDUP", 0.92),
        patch("config.SIMILARITY_THRESHOLD_RELATION", 0.5),
    ):
        # Patch module-level refs
        import db.action_log
        import db.chat
        import db.concepts
        import db.diagnostics
        import db.proposals
        import db.relations
        import db.reviews
        import db.topics

        original_knowledge = {}
        modules_to_patch = [
            db.topics,
            db.concepts,
            db.relations,
            db.reviews,
            db.chat,
            db.diagnostics,
            db.proposals,
            db.action_log,
        ]
        for mod in modules_to_patch:
            if hasattr(mod, "KNOWLEDGE_DB"):
                original_knowledge[mod] = mod.KNOWLEDGE_DB
                mod.KNOWLEDGE_DB = knowledge

        core.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Init SQLite only (not vectors yet)
        core._init_knowledge_db()
        core._init_chat_db()
        core._run_migrations()

        # Now init vector store with mocked embeddings
        import db.vectors as vectors_mod

        vectors_mod.reset()

        with (
            patch("services.embeddings.embed_text", side_effect=_fake_embed),
            patch("services.embeddings.embed_batch", side_effect=_fake_embed_batch),
            patch("services.embeddings.get_embedding_dim", return_value=768),
        ):
            vectors_mod.init_vector_store()
            yield tmp_path

        vectors_mod.reset()

        for mod, orig in original_knowledge.items():
            mod.KNOWLEDGE_DB = orig


class TestVectorCRUD:
    """Test basic vector store operations."""

    def test_upsert_and_search(self, vector_db):
        """Upsert a concept and find it via search."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_concept(1, "Machine Learning", "Study of algorithms that learn")
            results = vectors.search_similar_concepts("Machine Learning", limit=5)

        assert len(results) >= 1
        assert results[0]["id"] == 1
        assert results[0]["title"] == "Machine Learning"

    def test_delete_concept(self, vector_db):
        """Delete removes from vector store."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_concept(1, "Test Concept", "A test")
            vectors.delete_concept(1)
            results = vectors.search_similar_concepts("Test Concept", limit=5)

        # Should not find the deleted concept
        matching = [r for r in results if r["id"] == 1]
        assert len(matching) == 0

    def test_upsert_topic(self, vector_db):
        """Topics can be upserted and searched."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_topic(1, "Python Programming", "Learn Python")
            results = vectors.search_similar_topics("Python Programming", limit=5)

        assert len(results) >= 1
        assert results[0]["id"] == 1

    def test_delete_topic(self, vector_db):
        """Delete removes topic from vector store."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_topic(1, "Test Topic", "A test")
            vectors.delete_topic(1)
            results = vectors.search_similar_topics("Test Topic", limit=5)

        matching = [r for r in results if r["id"] == 1]
        assert len(matching) == 0

    def test_find_nearest_concepts(self, vector_db):
        """Find semantically similar concepts."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_concept(1, "Machine Learning", "Algorithms that learn from data")
            vectors.upsert_concept(2, "Deep Learning", "Neural networks with many layers")
            vectors.upsert_concept(3, "Cooking Pasta", "How to cook Italian food")

            neighbors = vectors.find_nearest_concepts(1, limit=5, score_threshold=0.0)

        # Should return concept 2 and 3 (not concept 1 itself)
        neighbor_ids = {n["id"] for n in neighbors}
        assert 1 not in neighbor_ids  # self excluded
        assert len(neighbors) >= 1

    def test_find_nearest_excludes_self(self, vector_db):
        """find_nearest_concepts never returns the queried concept."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_concept(10, "Test A", "Description A")
            vectors.upsert_concept(11, "Test B", "Description B")

            neighbors = vectors.find_nearest_concepts(10, limit=10, score_threshold=0.0)

        assert all(n["id"] != 10 for n in neighbors)

    def test_concept_similarity(self, vector_db):
        """Cosine similarity between two concepts."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_concept(1, "Test A", "Desc")
            vectors.upsert_concept(2, "Test B", "Desc")

            sim = vectors.concept_similarity(1, 2)

        assert isinstance(sim, float)
        assert 0.0 <= sim <= 1.0

    def test_concept_similarity_missing(self, vector_db):
        """Similarity returns 0.0 when a concept is missing."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            vectors.upsert_concept(1, "Test", "Desc")
            sim = vectors.concept_similarity(1, 999)

        assert sim == 0.0

    def test_collection_count(self, vector_db):
        """Collection count reflects insertions."""
        import db.vectors as vectors

        with patch("services.embeddings.embed_text", side_effect=_fake_embed):
            assert vectors.get_collection_count(vectors.CONCEPTS_COLLECTION) == 0
            vectors.upsert_concept(1, "A", "desc")
            assert vectors.get_collection_count(vectors.CONCEPTS_COLLECTION) == 1
            vectors.upsert_concept(2, "B", "desc")
            assert vectors.get_collection_count(vectors.CONCEPTS_COLLECTION) == 2


class TestReindex:
    """Test bulk reindex from SQLite."""

    def test_reindex_all(self, vector_db):
        """reindex_all rebuilds both collections from SQLite data."""
        import db.vectors as vectors

        # Add some data to SQLite
        db.add_concept("Concept A", "Desc A")
        db.add_concept("Concept B", "Desc B")
        db.add_topic("Topic A", "Desc TA")

        with (
            patch("services.embeddings.embed_text", side_effect=_fake_embed),
            patch("services.embeddings.embed_batch", side_effect=_fake_embed_batch),
            patch("services.embeddings.get_embedding_dim", return_value=768),
        ):
            result = vectors.reindex_all()

        assert result["concepts"] == 2
        assert result["topics"] >= 1
