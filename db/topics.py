"""
Topic CRUD operations, topic maps, and hierarchy queries.
"""

import os
import logging
import sqlite3
from typing import Dict, List, Optional

from db.core import _conn, _now_iso, _uid

logger = logging.getLogger("learn.db.topics")


def _vector_sync_disabled() -> bool:
    """Allow tests to disable automatic vector sync to avoid heavy model loads."""
    return os.environ.get("LEARN_DISABLE_VECTOR_SYNC") == "1"


# ============================================================================
# Vector store sync helpers (best-effort, non-fatal)
# ============================================================================


def _vector_upsert(topic_id: int, title: str, description: Optional[str] = None):
    """Sync a topic to the vector store. Silently skips on failure."""
    if _vector_sync_disabled():
        return
    try:
        from db.vectors import upsert_topic

        upsert_topic(topic_id, title, description)
    except Exception as e:
        logger.debug(f"Vector upsert skipped for topic #{topic_id}: {e}")


def _vector_delete(topic_id: int):
    """Remove a topic from the vector store. Silently skips on failure."""
    if _vector_sync_disabled():
        return
    try:
        from db.vectors import delete_topic

        delete_topic(topic_id)
    except Exception as e:
        logger.debug(f"Vector delete skipped for topic #{topic_id}: {e}")


# ============================================================================
# Topic CRUD
# ============================================================================


def add_topic(
    title: str, description: Optional[str] = None, parent_ids: Optional[List[int]] = None,
    *, user_id: Optional[str] = None,
) -> int:
    """Create a topic and optionally link it as a child of parent topic(s).
    Returns the new topic ID."""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()
    cursor = conn.execute(
        "INSERT INTO topics (title, description, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?)",
        (title, description, now, now, uid),
    )
    topic_id = cursor.lastrowid

    if parent_ids:
        for pid in parent_ids:
            if pid == topic_id:
                continue  # skip self-link
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO topic_relations "
                    "(parent_id, child_id, created_at) VALUES (?, ?, ?)",
                    (pid, topic_id, now),
                )
            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()

    # Sync to vector store (best-effort)
    _vector_upsert(topic_id, title, description)

    return topic_id


def get_topic(topic_id: int, *, user_id: Optional[str] = None) -> Optional[Dict]:
    """Get a single topic by ID."""
    uid = user_id or _uid()
    conn = _conn()
    row = conn.execute("SELECT * FROM topics WHERE id = ? AND user_id = ?", (topic_id, uid)).fetchone()
    conn.close()
    return dict(row) if row else None


def find_topic_by_title(title: str, *, user_id: Optional[str] = None) -> Optional[Dict]:
    """Find a topic by exact title (case-insensitive). Returns topic dict or None."""
    uid = user_id or _uid()
    conn = _conn()
    row = conn.execute("SELECT * FROM topics WHERE LOWER(title) = LOWER(?) AND user_id = ?", (title, uid)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_topic(topic_id: int, *, user_id: Optional[str] = None, **kwargs) -> bool:
    """Update topic fields. Returns True if topic was found."""
    uid = user_id or _uid()
    allowed = {"title", "description"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False

    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [topic_id, uid]

    conn = _conn()
    cursor = conn.execute(f"UPDATE topics SET {set_clause} WHERE id = ? AND user_id = ?", values)
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()

    # Sync title/description changes to vector store
    if updated and ("title" in fields or "description" in fields):
        topic = get_topic(topic_id)
        if topic:
            _vector_upsert(topic_id, topic["title"], topic.get("description"))

    return updated


def delete_topic(topic_id: int, *, user_id: Optional[str] = None) -> bool:
    """Delete a topic and its relation edges. Concepts that are still linked
    to other topics are preserved; orphaned concepts are also preserved."""
    uid = user_id or _uid()
    conn = _conn()
    # Verify ownership
    owner_check = conn.execute(
        "SELECT 1 FROM topics WHERE id = ? AND user_id = ?", (topic_id, uid)
    ).fetchone()
    if not owner_check:
        conn.close()
        return False
    conn.execute(
        "DELETE FROM topic_relations WHERE parent_id = ? OR child_id = ?", (topic_id, topic_id)
    )
    conn.execute("DELETE FROM concept_topics WHERE topic_id = ?", (topic_id,))
    cursor = conn.execute("DELETE FROM topics WHERE id = ? AND user_id = ?", (topic_id, uid))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()

    # Sync to vector store (best-effort)
    if deleted:
        _vector_delete(topic_id)

    return deleted


def link_topics(parent_id: int, child_id: int, *, user_id: Optional[str] = None) -> bool:
    """Create a parent\u2192child edge between two topics. Returns True on success.

    Rejects self-links and links that would create a cycle in the DAG.
    """
    if parent_id == child_id:
        return False
    conn = _conn()
    try:
        # Cycle detection: check if child_id is already an ancestor of parent_id.
        # If so, adding parent_id → child_id would create a cycle.
        cycle_check = conn.execute(
            """
            WITH RECURSIVE ancestors AS (
                SELECT parent_id AS id FROM topic_relations WHERE child_id = ?
                UNION ALL
                SELECT tr.parent_id
                FROM topic_relations tr
                JOIN ancestors a ON tr.child_id = a.id
            )
            SELECT 1 FROM ancestors WHERE id = ? LIMIT 1
        """,
            (parent_id, child_id),
        ).fetchone()
        if cycle_check:
            return False  # would create cycle

        conn.execute(
            "INSERT OR IGNORE INTO topic_relations "
            "(parent_id, child_id, created_at) VALUES (?, ?, ?)",
            (parent_id, child_id, _now_iso()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def unlink_topics(parent_id: int, child_id: int, *, user_id: Optional[str] = None) -> bool:
    """Remove a parent→child edge between two topics. Returns True if it existed."""
    conn = _conn()
    cursor = conn.execute(
        "DELETE FROM topic_relations WHERE parent_id = ? AND child_id = ?", (parent_id, child_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def get_all_topics(*, user_id: Optional[str] = None) -> List[Dict]:
    """Get all topics (flat list)."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute("SELECT * FROM topics WHERE user_id = ? ORDER BY title", (uid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topic_relations(*, user_id: Optional[str] = None) -> List[Dict]:
    """Get all topic→topic edges."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        "SELECT tr.* FROM topic_relations tr "
        "JOIN topics t ON t.id = tr.parent_id WHERE t.user_id = ?",
        (uid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topic_children(topic_id: int, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get child topics of a given topic."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        """
        SELECT t.* FROM topics t
        JOIN topic_relations tr ON t.id = tr.child_id
        WHERE tr.parent_id = ? AND t.user_id = ?
        ORDER BY t.title
    """,
        (topic_id, uid),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topic_parents(topic_id: int, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get parent topics of a given topic."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        """
        SELECT t.* FROM topics t
        JOIN topic_relations tr ON t.id = tr.parent_id
        WHERE tr.child_id = ? AND t.user_id = ?
        ORDER BY t.title
    """,
        (topic_id, uid),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_topics(query: str, limit: int = 20, *, user_id: Optional[str] = None) -> List[Dict]:
    """Search topics by title or description.

    Uses vector similarity search when available (semantic matching),
    falls back to FTS5 keyword search, then LIKE as last resort.
    """
    uid = user_id or _uid()
    # Try vector search first
    try:
        from db.vectors import search_similar_topics

        hits = search_similar_topics(query, limit=limit)
        if hits:
            ids = [h["id"] for h in hits]
            conn = _conn()
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"""
                SELECT t.* FROM topics t
                WHERE t.id IN ({placeholders}) AND t.user_id = ?
            """,
                ids + [uid],
            ).fetchall()
            conn.close()

            # Preserve vector similarity ordering
            id_order = {tid: i for i, tid in enumerate(ids)}
            results = [dict(r) for r in rows]
            results.sort(key=lambda d: id_order.get(d["id"], 999))
            return results
    except Exception:
        pass  # Fall through to FTS5

    # FTS5 fallback
    conn = _conn()
    try:
        fts_query = '"' + query.replace('"', '""') + '"'
        rows = conn.execute(
            """
            SELECT t.* FROM topics t
            JOIN topics_fts fts ON t.id = fts.rowid
            WHERE topics_fts MATCH ? AND t.user_id = ?
            ORDER BY rank
            LIMIT ?
        """,
            (fts_query, uid, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        pattern = f"%{query}%"
        rows = conn.execute(
            """
            SELECT * FROM topics
            WHERE (title LIKE ? OR description LIKE ?) AND user_id = ?
            ORDER BY title LIMIT ?
        """,
            (pattern, pattern, uid, limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
# Topic Map (lightweight, for context building)
# ============================================================================


def get_topic_map(*, user_id: Optional[str] = None) -> List[Dict]:
    """Get topic tree/DAG with summary stats per topic.
    Returns: [{id, title, description, concept_count, avg_mastery,
               due_count, parent_ids, child_ids}]"""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()

    topics = conn.execute("SELECT * FROM topics WHERE user_id = ? ORDER BY title", (uid,)).fetchall()
    relations = conn.execute(
        "SELECT tr.parent_id, tr.child_id FROM topic_relations tr "
        "JOIN topics t ON t.id = tr.parent_id WHERE t.user_id = ?",
        (uid,),
    ).fetchall()

    parent_map = {}
    child_map = {}
    for r in relations:
        parent_map.setdefault(r["child_id"], []).append(r["parent_id"])
        child_map.setdefault(r["parent_id"], []).append(r["child_id"])

    stats = conn.execute(
        """
        SELECT ct.topic_id,
               COUNT(c.id) as concept_count,
               ROUND(AVG(c.mastery_level), 1) as avg_mastery,
               SUM(CASE WHEN c.next_review_at IS NOT NULL
                        AND c.next_review_at <= ? THEN 1 ELSE 0 END) as due_count
        FROM concept_topics ct
        JOIN concepts c ON ct.concept_id = c.id
        WHERE c.user_id = ?
        GROUP BY ct.topic_id
    """,
        (now, uid),
    ).fetchall()
    stats_map = {s["topic_id"]: dict(s) for s in stats}

    result = []
    for t in topics:
        tid = t["id"]
        s = stats_map.get(tid, {})
        result.append(
            {
                "id": tid,
                "title": t["title"],
                "description": t["description"],
                "concept_count": s.get("concept_count", 0),
                "avg_mastery": s.get("avg_mastery", 0.0),
                "due_count": s.get("due_count", 0),
                "parent_ids": parent_map.get(tid, []),
                "child_ids": child_map.get(tid, []),
            }
        )

    conn.close()
    return result


# ============================================================================
# Hierarchical Topic Map (root-only, for compact context)
# ============================================================================


def get_hierarchical_topic_map(*, user_id: Optional[str] = None) -> List[Dict]:
    """Get root topics only, with aggregated stats from entire subtree.
    Uses a recursive CTE to compute subtree membership in SQL."""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()

    rows = conn.execute(
        """
        WITH RECURSIVE
        roots AS (
            SELECT id FROM topics
            WHERE user_id = ?
              AND id NOT IN (SELECT child_id FROM topic_relations)
        ),
        subtree AS (
            SELECT r.id AS root_id, r.id AS topic_id, 0 AS depth
            FROM roots r
            UNION ALL
            SELECT st.root_id, tr.child_id AS topic_id, st.depth + 1
            FROM subtree st
            JOIN topic_relations tr ON tr.parent_id = st.topic_id
            WHERE st.depth < 50
        ),
        subtopic_counts AS (
            SELECT root_id, COUNT(DISTINCT topic_id) - 1 AS subtopic_count
            FROM subtree
            GROUP BY root_id
        ),
        root_concepts AS (
            SELECT DISTINCT st.root_id, ct.concept_id
            FROM subtree st
            JOIN concept_topics ct ON ct.topic_id = st.topic_id
        )
        SELECT
            t.id,
            t.title,
            t.description,
            COALESCE(sc.subtopic_count, 0) AS subtopic_count,
            COUNT(DISTINCT rc.concept_id) AS total_concepts,
            COALESCE(ROUND(AVG(c.mastery_level), 1), 0.0) AS avg_mastery,
            COALESCE(SUM(CASE
                WHEN c.next_review_at IS NOT NULL AND c.next_review_at <= ?
                THEN 1 ELSE 0
            END), 0) AS due_count
        FROM roots r
        JOIN topics t ON t.id = r.id
        LEFT JOIN subtopic_counts sc ON sc.root_id = r.id
        LEFT JOIN root_concepts rc ON rc.root_id = r.id
        LEFT JOIN concepts c ON c.id = rc.concept_id
        GROUP BY t.id
        ORDER BY t.title
    """,
        (uid, now),
    ).fetchall()
    conn.close()

    return [dict(r) for r in rows]
