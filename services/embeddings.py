"""
Embedding service — generates vector embeddings for semantic search.

Uses sentence-transformers with a lazily-loaded singleton model.
Model choice is configured via config.EMBEDDING_MODEL.
"""

import logging
from typing import List, Optional

logger = logging.getLogger("learn.embeddings")

# Lazy singleton
_model = None
_model_name: Optional[str] = None


def _get_model():
    """Load the embedding model on first use (lazy singleton)."""
    global _model, _model_name
    if _model is not None:
        return _model

    from config import EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError(
            "sentence-transformers not installed. "
            "Run: pip install sentence-transformers"
        )

    logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
    _model = SentenceTransformer(EMBEDDING_MODEL)
    _model_name = EMBEDDING_MODEL
    logger.info(f"Embedding model loaded (dim={_model.get_sentence_embedding_dimension()})")
    return _model


def get_embedding_dim() -> int:
    """Return the dimensionality of the current embedding model."""
    return _get_model().get_sentence_embedding_dimension()


def embed_text(text: str) -> List[float]:
    """Generate an embedding vector for a single text string.

    Returns a list of floats (768-dim for all-mpnet-base-v2).
    """
    model = _get_model()
    embedding = model.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return embedding.tolist()


def embed_batch(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    """Generate embeddings for a batch of texts.

    More efficient than calling embed_text() in a loop —
    sentence-transformers parallelises encoding internally.

    Returns a list of embedding vectors (same order as input).
    """
    if not texts:
        return []
    model = _get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        show_progress_bar=len(texts) > 50,
    )
    return [e.tolist() for e in embeddings]


def reset():
    """Reset the singleton (for testing)."""
    global _model, _model_name
    _model = None
    _model_name = None
