"""
Vector store operations — Qdrant wrapper for semantic search.

Runs Qdrant in embedded/local mode (no separate server process).
Data is stored in VECTOR_STORE_PATH alongside the SQLite databases.

Collections:
  - concepts: concept title + description embeddings
  - topics:   topic title + description embeddings
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger("learn.vectors")

# Lazy singleton
_client = None

# Collection names
CONCEPTS_COLLECTION = "concepts"
TOPICS_COLLECTION = "topics"


def _get_client():
    """Get or create the Qdrant client (lazy singleton, embedded mode)."""
    global _client
    if _client is not None:
        return _client

    try:
        from qdrant_client import QdrantClient
    except ImportError:
        raise RuntimeError("qdrant-client not installed. Run: pip install qdrant-client")

    from config import VECTOR_STORE_PATH

    path = str(VECTOR_STORE_PATH)
    logger.info(f"Initializing Qdrant (embedded) at: {path}")
    _client = QdrantClient(path=path)
    return _client


def init_vector_store():
    """Initialize Qdrant collections if they don't exist.

    Called during db.init_databases() so both stores are ready together.
    Safe to call multiple times (idempotent).
    """
    try:
        from qdrant_client.models import Distance, VectorParams
    except ImportError:
        logger.warning("qdrant-client not installed — vector store disabled")
        return

    from services.embeddings import get_embedding_dim

    client = _get_client()
    dim = get_embedding_dim()

    for collection_name in (CONCEPTS_COLLECTION, TOPICS_COLLECTION):
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            logger.info(f"Created collection '{collection_name}' (dim={dim})")
        else:
            logger.debug(f"Collection '{collection_name}' already exists")


def _make_text(title: str, description: Optional[str]) -> str:
    """Combine title and description into a single text for embedding."""
    if description:
        return f"{title} — {description}"
    return title


# ============================================================================
# Concept operations
# ============================================================================


def upsert_concept(concept_id: int, title: str, description: Optional[str] = None):
    """Embed and upsert a concept into the vector store."""
    from qdrant_client.models import PointStruct

    from services.embeddings import embed_text

    text = _make_text(title, description)
    vector = embed_text(text)

    client = _get_client()
    client.upsert(
        collection_name=CONCEPTS_COLLECTION,
        points=[
            PointStruct(
                id=concept_id,
                vector=vector,
                payload={"title": title, "type": "concept"},
            )
        ],
    )
    logger.debug(f"Upserted concept #{concept_id}: {title}")


def delete_concept(concept_id: int):
    """Remove a concept from the vector store."""
    from qdrant_client.models import PointIdsList

    client = _get_client()
    client.delete(
        collection_name=CONCEPTS_COLLECTION,
        points_selector=PointIdsList(points=[concept_id]),
    )
    logger.debug(f"Deleted concept #{concept_id} from vector store")


def search_similar_concepts(
    query: str, limit: int = 10, score_threshold: float = 0.3
) -> List[Dict]:
    """Semantic search for concepts matching a query string.

    Returns list of dicts: [{id, title, score}, ...] ordered by similarity.
    """
    from services.embeddings import embed_text

    client = _get_client()
    query_vector = embed_text(query)

    response = client.query_points(
        collection_name=CONCEPTS_COLLECTION,
        query=query_vector,
        limit=limit,
        score_threshold=score_threshold,
    )

    return [
        {
            "id": hit.id,
            "title": hit.payload.get("title", ""),
            "score": round(hit.score, 4),
        }
        for hit in response.points
    ]


def find_nearest_concepts(
    concept_id: int,
    limit: int = 5,
    score_threshold: float = 0.4,
    exclude_ids: Optional[List[int]] = None,
) -> List[Dict]:
    """Find the N nearest concepts to a given concept (by vector similarity).

    Used for relationship discovery and multi-concept quiz clustering.
    Returns list of dicts: [{id, title, score}, ...] sorted by similarity.
    """
    from qdrant_client.models import FieldCondition, MatchValue

    client = _get_client()

    # Retrieve the concept's existing vector
    points = client.retrieve(
        collection_name=CONCEPTS_COLLECTION,
        ids=[concept_id],
        with_vectors=True,
    )
    if not points:
        logger.warning(f"Concept #{concept_id} not found in vector store")
        return []

    query_vector = points[0].vector

    # Build exclusion list (always exclude self)
    must_not = []
    all_exclude = [concept_id] + (exclude_ids or [])
    for eid in all_exclude:
        must_not.append(FieldCondition(key="id", match=MatchValue(value=eid)))

    # Qdrant doesn't filter by point ID via FieldCondition easily,
    # so we request extra results and filter post-hoc
    raw_limit = limit + len(all_exclude)
    response = client.query_points(
        collection_name=CONCEPTS_COLLECTION,
        query=query_vector,
        limit=raw_limit,
        score_threshold=score_threshold,
    )

    # Filter out excluded IDs
    exclude_set = set(all_exclude)
    filtered = [
        {
            "id": hit.id,
            "title": hit.payload.get("title", ""),
            "score": round(hit.score, 4),
        }
        for hit in response.points
        if hit.id not in exclude_set
    ]

    return filtered[:limit]


def concept_similarity(id_a: int, id_b: int) -> float:
    """Compute cosine similarity between two concepts in the vector store.

    Returns 0.0 if either concept is missing.
    Used by dedup detection as a replacement for _title_similarity.
    """
    client = _get_client()
    points = client.retrieve(
        collection_name=CONCEPTS_COLLECTION,
        ids=[id_a, id_b],
        with_vectors=True,
    )
    if len(points) < 2:
        return 0.0

    import numpy as np

    vec_a = np.array(points[0].vector)
    vec_b = np.array(points[1].vector)

    dot = np.dot(vec_a, vec_b)
    norm = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


# ============================================================================
# Topic operations
# ============================================================================


def upsert_topic(topic_id: int, title: str, description: Optional[str] = None):
    """Embed and upsert a topic into the vector store."""
    from qdrant_client.models import PointStruct

    from services.embeddings import embed_text

    text = _make_text(title, description)
    vector = embed_text(text)

    client = _get_client()
    client.upsert(
        collection_name=TOPICS_COLLECTION,
        points=[
            PointStruct(
                id=topic_id,
                vector=vector,
                payload={"title": title, "type": "topic"},
            )
        ],
    )
    logger.debug(f"Upserted topic #{topic_id}: {title}")


def delete_topic(topic_id: int):
    """Remove a topic from the vector store."""
    from qdrant_client.models import PointIdsList

    client = _get_client()
    client.delete(
        collection_name=TOPICS_COLLECTION,
        points_selector=PointIdsList(points=[topic_id]),
    )
    logger.debug(f"Deleted topic #{topic_id} from vector store")


def search_similar_topics(query: str, limit: int = 10, score_threshold: float = 0.3) -> List[Dict]:
    """Semantic search for topics matching a query string.

    Returns list of dicts: [{id, title, score}, ...] ordered by similarity.
    """
    from services.embeddings import embed_text

    client = _get_client()
    query_vector = embed_text(query)

    response = client.query_points(
        collection_name=TOPICS_COLLECTION,
        query=query_vector,
        limit=limit,
        score_threshold=score_threshold,
    )

    return [
        {
            "id": hit.id,
            "title": hit.payload.get("title", ""),
            "score": round(hit.score, 4),
        }
        for hit in response.points
    ]


# ============================================================================
# Bulk operations (migration / repair)
# ============================================================================


def reindex_all():
    """Rebuild the entire vector store from SQLite data.

    Drops and recreates both collections, then bulk-embeds all
    concepts and topics. Used by migrate_vectors.py and as a
    repair tool if the vector store drifts out of sync.
    """
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from db.core import _conn
    from services.embeddings import embed_batch, get_embedding_dim

    client = _get_client()
    dim = get_embedding_dim()

    # --- Concepts ---
    if client.collection_exists(CONCEPTS_COLLECTION):
        client.delete_collection(CONCEPTS_COLLECTION)
    client.create_collection(
        collection_name=CONCEPTS_COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    conn = _conn()
    concept_rows = conn.execute(
        "SELECT id, title, description FROM concepts ORDER BY id"
    ).fetchall()
    conn.close()

    if concept_rows:
        texts = [_make_text(r["title"], r["description"]) for r in concept_rows]
        vectors = embed_batch(texts)
        points = [
            PointStruct(
                id=row["id"],
                vector=vec,
                payload={"title": row["title"], "type": "concept"},
            )
            for row, vec in zip(concept_rows, vectors)
        ]
        # Upsert in batches of 100
        for i in range(0, len(points), 100):
            client.upsert(
                collection_name=CONCEPTS_COLLECTION,
                points=points[i : i + 100],
            )
        logger.info(f"Reindexed {len(points)} concepts")

    # --- Topics ---
    if client.collection_exists(TOPICS_COLLECTION):
        client.delete_collection(TOPICS_COLLECTION)
    client.create_collection(
        collection_name=TOPICS_COLLECTION,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )

    conn = _conn()
    topic_rows = conn.execute("SELECT id, title, description FROM topics ORDER BY id").fetchall()
    conn.close()

    if topic_rows:
        texts = [_make_text(r["title"], r["description"]) for r in topic_rows]
        vectors = embed_batch(texts)
        points = [
            PointStruct(
                id=row["id"],
                vector=vec,
                payload={"title": row["title"], "type": "topic"},
            )
            for row, vec in zip(topic_rows, vectors)
        ]
        for i in range(0, len(points), 100):
            client.upsert(
                collection_name=TOPICS_COLLECTION,
                points=points[i : i + 100],
            )
        logger.info(f"Reindexed {len(points)} topics")

    return {
        "concepts": len(concept_rows),
        "topics": len(topic_rows) if topic_rows else 0,
    }


def get_collection_count(collection_name: str) -> int:
    """Get the number of points in a collection (for diagnostics)."""
    client = _get_client()
    if not client.collection_exists(collection_name):
        return 0
    info = client.get_collection(collection_name)
    return info.points_count


def reset():
    """Reset the singleton (for testing)."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
