"""
Concept CRUD operations, search, and detail queries.
"""

import os
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from db.core import _conn, _normalize_dt_str, _now_iso, _uid

logger = logging.getLogger("learn.db.concepts")


def _vector_sync_disabled() -> bool:
    """Allow tests to disable automatic vector sync to avoid heavy model loads."""
    return os.environ.get("LEARN_DISABLE_VECTOR_SYNC") == "1"


# ============================================================================
# Vector store sync helpers (best-effort, non-fatal)
# ============================================================================


def _vector_upsert(concept_id: int, title: str, description: Optional[str] = None):
    """Sync a concept to the vector store. Silently skips on failure."""
    if _vector_sync_disabled():
        return
    try:
        from db.vectors import upsert_concept

        upsert_concept(concept_id, title, description)
    except Exception as e:
        logger.debug(f"Vector upsert skipped for concept #{concept_id}: {e}")


def _vector_delete(concept_id: int):
    """Remove a concept from the vector store. Silently skips on failure."""
    if _vector_sync_disabled():
        return
    try:
        from db.vectors import delete_concept

        delete_concept(concept_id)
    except Exception as e:
        logger.debug(f"Vector delete skipped for concept #{concept_id}: {e}")


# ============================================================================
# Concept CRUD
# ============================================================================


def add_concept(
    title: str,
    description: Optional[str] = None,
    topic_ids: Optional[List[int]] = None,
    next_review_at: Optional[str] = None,
    *,
    user_id: Optional[str] = None,
) -> int:
    """Create a concept and optionally link it to topic(s).
    If next_review_at is None, defaults to tomorrow.
    Returns the new concept ID."""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()

    if next_review_at is None:
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        next_review_at = tomorrow
    else:
        next_review_at = _normalize_dt_str(next_review_at) or next_review_at

    try:
        cursor = conn.execute(
            """INSERT INTO concepts
               (title, description, next_review_at, created_at, updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, description, next_review_at, now, now, uid),
        )
    except sqlite3.IntegrityError:
        # UNIQUE constraint on title — concept already exists.
        # Return the existing concept's ID instead of creating a duplicate.
        # NOTE: UNIQUE index is on title alone; future migration will make it (user_id, title)
        row = conn.execute(
            "SELECT id FROM concepts WHERE LOWER(title) = LOWER(?) AND user_id = ?", (title, uid)
        ).fetchone()
        conn.close()
        if row:
            return row["id"]
        raise  # Shouldn't happen, but re-raise if we can't find the match

    concept_id = cursor.lastrowid

    if topic_ids:
        for tid in topic_ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO concept_topics (concept_id, topic_id) VALUES (?, ?)",
                    (concept_id, tid),
                )
            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()

    # Sync to vector store (best-effort)
    _vector_upsert(concept_id, title, description)

    return concept_id


def find_concept_by_title(title: str, *, user_id: Optional[str] = None) -> Optional[Dict]:
    """Find a concept by exact title (case-insensitive). Returns concept with topic_ids or None."""
    uid = user_id or _uid()
    conn = _conn()
    row = conn.execute("SELECT * FROM concepts WHERE LOWER(title) = LOWER(?) AND user_id = ?", (title, uid)).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    topic_rows = conn.execute(
        "SELECT topic_id FROM concept_topics WHERE concept_id = ?", (d["id"],)
    ).fetchall()
    d["topic_ids"] = [r["topic_id"] for r in topic_rows]
    conn.close()
    return d


def get_concept(concept_id: int, *, user_id: Optional[str] = None) -> Optional[Dict]:
    """Get a single concept by ID with its topic IDs."""
    uid = user_id or _uid()
    conn = _conn()
    row = conn.execute("SELECT * FROM concepts WHERE id = ? AND user_id = ?", (concept_id, uid)).fetchone()
    if not row:
        conn.close()
        return None

    concept = dict(row)
    topic_rows = conn.execute(
        "SELECT topic_id FROM concept_topics WHERE concept_id = ?", (concept_id,)
    ).fetchall()
    concept["topic_ids"] = [r["topic_id"] for r in topic_rows]
    conn.close()
    return concept


def update_concept(concept_id: int, *, user_id: Optional[str] = None, **kwargs) -> bool:
    """Update concept fields. Returns True if concept was found.
    Accepts: title, description, mastery_level, ease_factor, interval_days,
             next_review_at, last_reviewed_at, review_count,
             last_quiz_generator_output."""
    uid = user_id or _uid()
    allowed = {
        "title",
        "description",
        "mastery_level",
        "ease_factor",
        "interval_days",
        "next_review_at",
        "last_reviewed_at",
        "review_count",
        "last_quiz_generator_output",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False

    for dt_key in ("next_review_at", "last_reviewed_at"):
        if dt_key in fields and isinstance(fields[dt_key], str):
            fields[dt_key] = _normalize_dt_str(fields[dt_key]) or fields[dt_key]

    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [concept_id, uid]

    conn = _conn()
    cursor = conn.execute(f"UPDATE concepts SET {set_clause} WHERE id = ? AND user_id = ?", values)
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()

    # Sync title/description changes to vector store
    if updated and ("title" in fields or "description" in fields):
        concept = get_concept(concept_id)
        if concept:
            _vector_upsert(concept_id, concept["title"], concept.get("description"))

    return updated


def delete_concept(concept_id: int, *, user_id: Optional[str] = None) -> bool:
    """Delete a concept and all its relations, remarks, and review logs."""
    uid = user_id or _uid()
    conn = _conn()
    # Verify ownership before cascading deletes
    owner_check = conn.execute(
        "SELECT 1 FROM concepts WHERE id = ? AND user_id = ?", (concept_id, uid)
    ).fetchone()
    if not owner_check:
        conn.close()
        return False
    conn.execute("DELETE FROM concept_topics WHERE concept_id = ?", (concept_id,))
    conn.execute("DELETE FROM concept_remarks WHERE concept_id = ?", (concept_id,))
    conn.execute("DELETE FROM review_log WHERE concept_id = ?", (concept_id,))
    conn.execute(
        "DELETE FROM concept_relations WHERE concept_id_low = ? OR concept_id_high = ?",
        (concept_id, concept_id),
    )
    cursor = conn.execute("DELETE FROM concepts WHERE id = ? AND user_id = ?", (concept_id, uid))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()

    # Sync to vector store (best-effort)
    if deleted:
        _vector_delete(concept_id)

    return deleted


def link_concept(concept_id: int, topic_ids: List[int]) -> int:
    """Link an existing concept to additional topic(s).
    Returns the number of new links created."""
    conn = _conn()
    count = 0
    for tid in topic_ids:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO concept_topics (concept_id, topic_id) VALUES (?, ?)",
                (concept_id, tid),
            )
            count += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return count


def unlink_concept(concept_id: int, topic_id: int) -> bool:
    """Remove a concept from a topic. Returns True if a link existed."""
    conn = _conn()
    cursor = conn.execute(
        "DELETE FROM concept_topics WHERE concept_id = ? AND topic_id = ?", (concept_id, topic_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def get_concepts_for_topic(topic_id: int, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get all concepts linked to a topic, with latest remark."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        """
        SELECT c.*,
               c.remark_summary AS latest_remark
        FROM concepts c
        JOIN concept_topics ct ON c.id = ct.concept_id
        WHERE ct.topic_id = ? AND c.user_id = ?
        ORDER BY c.next_review_at ASC NULLS LAST
    """,
        (topic_id, uid),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_concepts(limit: int = 10, offset: int = 0, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get concepts due for review (next_review_at <= now), ordered by most overdue."""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()
    rows = conn.execute(
        """
        SELECT c.*,
               c.remark_summary AS latest_remark,
               GROUP_CONCAT(ct.topic_id) as topic_id_list
        FROM concepts c
        LEFT JOIN concept_topics ct ON c.id = ct.concept_id
        WHERE c.next_review_at IS NOT NULL AND c.next_review_at <= ? AND c.user_id = ?
        GROUP BY c.id
        ORDER BY c.next_review_at ASC
        LIMIT ? OFFSET ?
    """,
        (now, uid, limit, offset),
    ).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        tid_str = d.pop("topic_id_list", None)
        d["topic_ids"] = [int(x) for x in tid_str.split(",")] if tid_str else []
        results.append(d)
    return results


def get_next_review_concept(*, user_id: Optional[str] = None) -> Optional[Dict]:
    """Get the single concept with the nearest next_review_at, regardless
    of whether it's overdue or upcoming. Returns None if no concepts have
    a scheduled review."""
    uid = user_id or _uid()
    conn = _conn()
    row = conn.execute("""
        SELECT c.*,
               c.remark_summary AS latest_remark,
               GROUP_CONCAT(ct.topic_id) as topic_id_list
        FROM concepts c
        LEFT JOIN concept_topics ct ON c.id = ct.concept_id
        WHERE c.next_review_at IS NOT NULL AND c.user_id = ?
        GROUP BY c.id
        ORDER BY c.next_review_at ASC
        LIMIT 1
    """, (uid,)).fetchone()
    conn.close()

    if not row:
        return None
    d = dict(row)
    tid_str = d.pop("topic_id_list", None)
    d["topic_ids"] = [int(x) for x in tid_str.split(",")] if tid_str else []
    return d


def get_all_concepts_summary(limit: int | None = None, offset: int = 0, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get all concepts with title, description, review count, topic names/IDs,
    and scheduling fields. Used by dedup agent and graph visualization.
    Optional limit/offset for paginated access."""
    uid = user_id or _uid()
    conn = _conn()
    sql = """
        SELECT c.id, c.title, c.description, c.review_count, c.mastery_level,
               c.next_review_at, c.interval_days,
               GROUP_CONCAT(DISTINCT t.title) as topic_names,
               GROUP_CONCAT(DISTINCT ct.topic_id) as topic_id_list
        FROM concepts c
        LEFT JOIN concept_topics ct ON c.id = ct.concept_id
        LEFT JOIN topics t ON ct.topic_id = t.id
        WHERE c.user_id = ?
        GROUP BY c.id
        ORDER BY c.id
    """
    params: list = [uid]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        tid_str = d.pop("topic_id_list", None)
        d["topic_ids"] = [int(x) for x in tid_str.split(",")] if tid_str else []
        results.append(d)
    return results


def get_concept_topic_edges(*, user_id: Optional[str] = None) -> List[Dict]:
    """All concept→topic membership edges for graph visualization."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        "SELECT ct.concept_id, ct.topic_id FROM concept_topics ct "
        "JOIN concepts c ON c.id = ct.concept_id WHERE c.user_id = ?",
        (uid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_count(*, user_id: Optional[str] = None) -> int:
    """Count concepts currently due for review."""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM concepts "
        "WHERE next_review_at IS NOT NULL AND next_review_at <= ? AND user_id = ?",
        (now, uid),
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_due_forecast(range_type: str = "weeks", *, user_id: Optional[str] = None) -> Dict:
    """Return counts of concepts due per upcoming time bucket, plus an Overdue bucket.

    Uses rolling windows (not calendar week numbers) so bucket boundaries are
    always relative to today, regardless of the day of the week.

    Args:
        range_type: "days"   → 7 windows of 1 day each starting from today
                    "weeks"  → 7 windows of 7 days each starting from today
                    "months" → 7 windows of 30 days each starting from today

    Returns:
        {
          "range_type": str,
          "overdue_count": int,
          "buckets": [
            {"label": str, "bucket_key": str, "count": int, "avg_mastery": float},
            ...  (7 entries, bucket_key "0".."6")
          ]
        }

    Raises:
        ValueError: if range_type is not one of the accepted values.
    """
    if range_type not in ("days", "weeks", "months"):
        raise ValueError(
            f"Invalid range_type {range_type!r}. Must be 'days', 'weeks', or 'months'."
        )

    window_sizes = {"days": 1, "weeks": 7, "months": 30}
    window_days = window_sizes[range_type]
    num_buckets = 7

    uid = user_id or _uid()
    conn = _conn()
    today = datetime.now().date().isoformat()

    # --- Overdue bucket ---
    overdue_row = conn.execute("""
        SELECT COUNT(*) as cnt, COALESCE(AVG(mastery_level), 0) as avg_m
        FROM concepts
        WHERE next_review_at IS NOT NULL
          AND DATE(next_review_at) < DATE(?)
          AND user_id = ?
    """, (today, uid)).fetchone()
    overdue_count = overdue_row["cnt"] if overdue_row else 0
    # Not included in main buckets list — returned separately for chart rendering

    # --- Rolling window buckets ---
    buckets = []
    for i in range(num_buckets):
        start_offset = i * window_days
        end_offset = (i + 1) * window_days

        row = conn.execute(
            """
            SELECT COUNT(*) as cnt, COALESCE(AVG(mastery_level), 0) as avg_m
            FROM concepts
            WHERE next_review_at IS NOT NULL
                            AND DATE(next_review_at) >= DATE(?, ? || ' days')
                            AND DATE(next_review_at) < DATE(?, ? || ' days')
                            AND user_id = ?
                        """,
                        (today, str(start_offset), today, str(end_offset), uid),
        ).fetchone()

        count = row["cnt"] if row else 0
        avg_mastery = round(row["avg_m"], 1) if row else 0.0

        # Human-readable label
        if range_type == "days":
            if i == 0:
                label = "Today"
            elif i == 1:
                label = "Tomorrow"
            else:
                label = f"Day +{i}"
        elif range_type == "weeks":
            if i == 0:
                label = "This week"
            elif i == 1:
                label = "Next week"
            else:
                label = f"Week +{i}"
        else:  # months
            if i == 0:
                label = "This month"
            elif i == 1:
                label = "Next month"
            else:
                label = f"Month +{i}"

        buckets.append(
            {
                "label": label,
                "bucket_key": str(i),
                "count": count,
                "avg_mastery": avg_mastery,
            }
        )

    conn.close()

    return {
        "range_type": range_type,
        "overdue_count": overdue_count,
        "buckets": buckets,
    }


def get_forecast_bucket_concepts(range_type: str, bucket_key: str, *, user_id: Optional[str] = None) -> List[Dict]:
    """Return full concept list for one forecast bucket (for on-click detail).

    bucket_key "overdue" → concepts where next_review_at < today
    bucket_key "0".."6"  → concepts in rolling window bucket i
    Results are sorted by mastery_level ASC (worst first).

    Raises:
        ValueError: if range_type is invalid.
    """
    window_sizes = {"days": 1, "weeks": 7, "months": 30}
    if range_type not in window_sizes:
        raise ValueError(
            f"Invalid range_type {range_type!r}. Must be 'days', 'weeks', or 'months'."
        )

    window_days = window_sizes[range_type]
    conn = _conn()
    uid = user_id or _uid()
    today = datetime.now().date().isoformat()

    if bucket_key == "overdue":
        rows = conn.execute("""
            SELECT c.id, c.title, c.mastery_level, c.next_review_at,
                   c.interval_days, c.review_count
            FROM concepts c
            WHERE c.next_review_at IS NOT NULL
              AND DATE(c.next_review_at) < DATE(?)
              AND c.user_id = ?
            ORDER BY c.mastery_level ASC
        """, (today, uid)).fetchall()
    else:
        try:
            i = int(bucket_key)
        except ValueError:
            conn.close()
            return []
        start_offset = i * window_days
        end_offset = (i + 1) * window_days
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.mastery_level, c.next_review_at,
                   c.interval_days, c.review_count
            FROM concepts c
            WHERE c.next_review_at IS NOT NULL
              AND DATE(c.next_review_at) >= DATE(?, ? || ' days')
              AND DATE(c.next_review_at) < DATE(?, ? || ' days')
              AND c.user_id = ?
            ORDER BY c.mastery_level ASC
            """,
            (today, str(start_offset), today, str(end_offset), uid),
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def get_all_concepts_with_topics(*, user_id: Optional[str] = None) -> List[Dict]:
    """Get all concepts with structured topic data and latest remark.
    Returns list of dicts, each with a 'topics' list of {id, title} dicts.
    Used by the web UI concepts page."""
    uid = user_id or _uid()
    conn = _conn()
    # Main concept query
    rows = conn.execute("""
        SELECT c.*,
               c.remark_summary AS latest_remark
        FROM concepts c
        WHERE c.user_id = ?
        ORDER BY c.next_review_at ASC NULLS LAST
    """, (uid,)).fetchall()

    # Topic links — fetch all at once (faster than N+1)
    topic_links = conn.execute("""
        SELECT ct.concept_id, t.id as topic_id, t.title as topic_title
        FROM concept_topics ct
        JOIN topics t ON ct.topic_id = t.id
        ORDER BY t.title
    """).fetchall()
    conn.close()

    # Build concept_id → [{id, title}] map
    from collections import defaultdict

    topic_map = defaultdict(list)
    for link in topic_links:
        topic_map[link["concept_id"]].append(
            {
                "id": link["topic_id"],
                "title": link["topic_title"],
            }
        )

    results = []
    for r in rows:
        d = dict(r)
        d["topics"] = topic_map.get(d["id"], [])
        results.append(d)
    return results


def search_concepts(query: str, limit: int = 20, *, user_id: Optional[str] = None) -> List[Dict]:
    """Search concepts by title or description.

    Uses vector similarity search when available (semantic matching),
    falls back to FTS5 keyword search, then LIKE as last resort.
    """
    uid = user_id or _uid()
    # Try vector search first
    try:
        from db.vectors import search_similar_concepts

        hits = search_similar_concepts(query, limit=limit)
        if hits:
            ids = [h["id"] for h in hits]
            conn = _conn()
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"""
                SELECT c.*,
                       GROUP_CONCAT(ct.topic_id) as topic_id_list
                FROM concepts c
                LEFT JOIN concept_topics ct ON c.id = ct.concept_id
                WHERE c.id IN ({placeholders}) AND c.user_id = ?
                GROUP BY c.id
            """,
                ids + [uid],
            ).fetchall()
            conn.close()

            # Preserve vector similarity ordering
            id_order = {cid: i for i, cid in enumerate(ids)}
            results = []
            for r in rows:
                d = dict(r)
                tid_str = d.pop("topic_id_list", None)
                d["topic_ids"] = [int(x) for x in tid_str.split(",")] if tid_str else []
                results.append(d)
            if results:
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
            SELECT c.*,
                   GROUP_CONCAT(ct.topic_id) as topic_id_list
            FROM concepts c
            JOIN concepts_fts fts ON c.id = fts.rowid
            LEFT JOIN concept_topics ct ON c.id = ct.concept_id
            WHERE concepts_fts MATCH ? AND c.user_id = ?
            GROUP BY c.id
            ORDER BY rank
            LIMIT ?
        """,
            (fts_query, uid, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        pattern = f"%{query}%"
        rows = conn.execute(
            """
            SELECT c.*,
                   GROUP_CONCAT(ct.topic_id) as topic_id_list
            FROM concepts c
            LEFT JOIN concept_topics ct ON c.id = ct.concept_id
            WHERE (c.title LIKE ? OR c.description LIKE ?) AND c.user_id = ?
            GROUP BY c.id
            ORDER BY c.title
            LIMIT ?
        """,
            (pattern, pattern, uid, limit),
        ).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        tid_str = d.pop("topic_id_list", None)
        d["topic_ids"] = [int(x) for x in tid_str.split(",")] if tid_str else []
        results.append(d)
    return results


# ============================================================================
# Concept Detail (for fetch loop)
# ============================================================================


def get_concept_detail(concept_id: int, *, user_id: Optional[str] = None) -> Optional[Dict]:
    """Get full concept detail: all fields + all remarks + last 5 reviews.
    This is the 'deep dive' query used by the fetch loop."""
    concept = get_concept(concept_id, user_id=user_id)
    if not concept:
        return None

    conn = _conn()

    # Full remark history (source of truth from concept_remarks table)
    remarks = conn.execute(
        """
        SELECT id, content, created_at FROM concept_remarks
        WHERE concept_id = ? ORDER BY id DESC LIMIT 10
    """,
        (concept_id,),
    ).fetchall()
    concept["remarks"] = [dict(r) for r in remarks]

    # Cached summary (used by pipeline/context for LLM)
    summary_row = conn.execute(
        "SELECT remark_summary, remark_updated_at, last_quiz_generator_output "
        "FROM concepts WHERE id = ?",
        (concept_id,),
    ).fetchone()
    if summary_row:
        concept["remark_summary"] = summary_row["remark_summary"]
        concept["remark_updated_at"] = summary_row["remark_updated_at"]
        concept["last_quiz_generator_output"] = summary_row["last_quiz_generator_output"]

    reviews = conn.execute(
        """
        SELECT id, question_asked, user_response, quality, llm_assessment, reviewed_at
        FROM review_log
        WHERE concept_id = ? ORDER BY id DESC LIMIT 5
    """,
        (concept_id,),
    ).fetchall()
    concept["recent_reviews"] = [dict(r) for r in reviews]

    topics = conn.execute(
        """
        SELECT t.id, t.title FROM topics t
        JOIN concept_topics ct ON t.id = ct.topic_id
        WHERE ct.concept_id = ?
    """,
        (concept_id,),
    ).fetchall()
    concept["topics"] = [dict(t) for t in topics]

    conn.close()
    return concept
