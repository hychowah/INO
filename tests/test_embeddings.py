"""
Tests for the embedding service (services/embeddings.py).
Uses mocked sentence-transformers to avoid loading a real model.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from services import embeddings


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure each test starts with a fresh singleton."""
    embeddings.reset()
    yield
    embeddings.reset()


def _make_mock_model(dim=768):
    """Create a mock SentenceTransformer."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = dim

    def fake_encode(text_or_texts, **kwargs):
        if isinstance(text_or_texts, str):
            return np.random.default_rng(hash(text_or_texts) % 2**32).random(dim).astype(np.float32)
        return np.array(
            [
                np.random.default_rng(hash(t) % 2**32).random(dim).astype(np.float32)
                for t in text_or_texts
            ]
        )

    model.encode.side_effect = fake_encode
    return model


class TestEmbedText:
    def test_returns_list_of_floats(self):
        mock_model = _make_mock_model()
        embeddings._model = mock_model
        embeddings._model_name = "test"
        result = embeddings.embed_text("hello world")

        assert isinstance(result, list)
        assert len(result) == 768
        assert all(isinstance(x, float) for x in result)

    def test_deterministic_same_input(self):
        mock_model = _make_mock_model()
        embeddings._model = mock_model
        embeddings._model_name = "test"

        r1 = embeddings.embed_text("test phrase")
        r2 = embeddings.embed_text("test phrase")
        assert r1 == r2

    def test_different_input_different_output(self):
        mock_model = _make_mock_model()
        embeddings._model = mock_model
        embeddings._model_name = "test"

        r1 = embeddings.embed_text("concept one")
        r2 = embeddings.embed_text("concept two")
        assert r1 != r2


class TestEmbedBatch:
    def test_empty_list(self):
        result = embeddings.embed_batch([])
        assert result == []

    def test_batch_returns_correct_count(self):
        mock_model = _make_mock_model()
        embeddings._model = mock_model
        embeddings._model_name = "test"

        texts = ["a", "b", "c"]
        result = embeddings.embed_batch(texts)
        assert len(result) == 3
        assert all(len(v) == 768 for v in result)

    def test_batch_preserves_order(self):
        mock_model = _make_mock_model()
        embeddings._model = mock_model
        embeddings._model_name = "test"

        texts = ["first", "second"]
        batch_result = embeddings.embed_batch(texts)
        single_results = [embeddings.embed_text(t) for t in texts]

        assert batch_result[0] == single_results[0]
        assert batch_result[1] == single_results[1]


class TestGetEmbeddingDim:
    def test_returns_model_dim(self):
        mock_model = _make_mock_model(dim=384)
        embeddings._model = mock_model
        embeddings._model_name = "test"

        assert embeddings.get_embedding_dim() == 384


class TestReset:
    def test_reset_clears_model(self):
        mock_model = _make_mock_model()
        embeddings._model = mock_model
        embeddings._model_name = "test"

        embeddings.reset()
        assert embeddings._model is None
        assert embeddings._model_name is None
