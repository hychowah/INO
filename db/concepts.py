"""
Concept CRUD operations, search, and detail queries.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from db.core import _conn, _now_iso, _normalize_dt_str


# ============================================================================
# Concept CRUD
# ============================================================================

def add_concept(title: str, description: Optional[str] = None,
                topic_ids: Optional[List[int]] = None,
                next_review_at: Optional[str] = None) -> int:
    """Create a concept and optionally link it to topic(s).
    If next_review_at is None, defaults to tomorrow.
    Returns the new concept ID."""
    conn = _conn()
    now = _now_iso()

    if next_review_at is None:
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
        next_review_at = tomorrow
    else:
        next_review_at = _normalize_dt_str(next_review_at) or next_review_at

    cursor = conn.execute(
        """INSERT INTO concepts
           (title, description, next_review_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (title, description, next_review_at, now, now)
    )
    concept_id = cursor.lastrowid

    if topic_ids:
        for tid in topic_ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO concept_topics (concept_id, topic_id) VALUES (?, ?)",
                    (concept_id, tid)
                )
            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()
    return concept_id


def get_concept(concept_id: int) -> Optional[Dict]:
    """Get a single concept by ID with its topic IDs."""
    conn = _conn()
    row = conn.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
    if not row:
        conn.close()
        return None

    concept = dict(row)
    topic_rows = conn.execute(
        "SELECT topic_id FROM concept_topics WHERE concept_id = ?",
        (concept_id,)
    ).fetchall()
    concept['topic_ids'] = [r['topic_id'] for r in topic_rows]
    conn.close()
    return concept


def update_concept(concept_id: int, **kwargs) -> bool:
    """Update concept fields. Returns True if concept was found.
    Accepts: title, description, mastery_level, ease_factor, interval_days,
             next_review_at, last_reviewed_at, review_count."""
    allowed = {
        'title', 'description', 'mastery_level', 'ease_factor',
        'interval_days', 'next_review_at', 'last_reviewed_at', 'review_count'
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False

    for dt_key in ('next_review_at', 'last_reviewed_at'):
        if dt_key in fields and isinstance(fields[dt_key], str):
            fields[dt_key] = _normalize_dt_str(fields[dt_key]) or fields[dt_key]

    fields['updated_at'] = _now_iso()
    set_clause = ', '.join(f'{k} = ?' for k in fields)
    values = list(fields.values()) + [concept_id]

    conn = _conn()
    cursor = conn.execute(f"UPDATE concepts SET {set_clause} WHERE id = ?", values)
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def delete_concept(concept_id: int) -> bool:
    """Delete a concept and all its relations, remarks, and review logs."""
    conn = _conn()
    conn.execute("DELETE FROM concept_topics WHERE concept_id = ?", (concept_id,))
    conn.execute("DELETE FROM concept_remarks WHERE concept_id = ?", (concept_id,))
    conn.execute("DELETE FROM review_log WHERE concept_id = ?", (concept_id,))
    cursor = conn.execute("DELETE FROM concepts WHERE id = ?", (concept_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
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
                (concept_id, tid)
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
        "DELETE FROM concept_topics WHERE concept_id = ? AND topic_id = ?",
        (concept_id, topic_id)
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def get_concepts_for_topic(topic_id: int) -> List[Dict]:
    """Get all concepts linked to a topic, with latest remark."""
    conn = _conn()
    rows = conn.execute("""
        SELECT c.*,
               (SELECT content FROM concept_remarks
                WHERE concept_id = c.id ORDER BY id DESC LIMIT 1) as latest_remark
        FROM concepts c
        JOIN concept_topics ct ON c.id = ct.concept_id
        WHERE ct.topic_id = ?
        ORDER BY c.next_review_at ASC NULLS LAST
    """, (topic_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_due_concepts(limit: int = 10) -> List[Dict]:
    """Get concepts due for review (next_review_at <= now), ordered by most overdue."""
    conn = _conn()
    now = _now_iso()
    rows = conn.execute("""
        SELECT c.*,
               (SELECT content FROM concept_remarks
                WHERE concept_id = c.id ORDER BY id DESC LIMIT 1) as latest_remark,
               GROUP_CONCAT(ct.topic_id) as topic_id_list
        FROM concepts c
        LEFT JOIN concept_topics ct ON c.id = ct.concept_id
        WHERE c.next_review_at IS NOT NULL AND c.next_review_at <= ?
        GROUP BY c.id
        ORDER BY c.next_review_at ASC
        LIMIT ?
    """, (now, limit)).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        tid_str = d.pop('topic_id_list', None)
        d['topic_ids'] = [int(x) for x in tid_str.split(',')] if tid_str else []
        results.append(d)
    return results


def get_all_concepts_summary() -> List[Dict]:
    """Get all concepts with title, description, review count, and topic names.
    Lightweight query used by the dedup agent."""
    conn = _conn()
    rows = conn.execute("""
        SELECT c.id, c.title, c.description, c.review_count, c.mastery_level,
               GROUP_CONCAT(t.title, ', ') as topic_names
        FROM concepts c
        LEFT JOIN concept_topics ct ON c.id = ct.concept_id
        LEFT JOIN topics t ON ct.topic_id = t.id
        GROUP BY c.id
        ORDER BY c.id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_concepts_with_topics() -> List[Dict]:
    """Get all concepts with structured topic data and latest remark.
    Returns list of dicts, each with a 'topics' list of {id, title} dicts.
    Used by the web UI concepts page."""
    conn = _conn()
    # Main concept query
    rows = conn.execute("""
        SELECT c.*,
               (SELECT content FROM concept_remarks
                WHERE concept_id = c.id ORDER BY id DESC LIMIT 1) as latest_remark
        FROM concepts c
        ORDER BY c.next_review_at ASC NULLS LAST
    """).fetchall()

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
        topic_map[link['concept_id']].append({
            'id': link['topic_id'],
            'title': link['topic_title'],
        })

    results = []
    for r in rows:
        d = dict(r)
        d['topics'] = topic_map.get(d['id'], [])
        results.append(d)
    return results


def search_concepts(query: str, limit: int = 20) -> List[Dict]:
    """Search concepts by title or description. Uses FTS5 when available, LIKE fallback."""
    conn = _conn()
    try:
        fts_query = '"' + query.replace('"', '""') + '"'
        rows = conn.execute("""
            SELECT c.*,
                   GROUP_CONCAT(ct.topic_id) as topic_id_list
            FROM concepts c
            JOIN concepts_fts fts ON c.id = fts.rowid
            LEFT JOIN concept_topics ct ON c.id = ct.concept_id
            WHERE concepts_fts MATCH ?
            GROUP BY c.id
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
    except sqlite3.OperationalError:
        pattern = f'%{query}%'
        rows = conn.execute("""
            SELECT c.*,
                   GROUP_CONCAT(ct.topic_id) as topic_id_list
            FROM concepts c
            LEFT JOIN concept_topics ct ON c.id = ct.concept_id
            WHERE c.title LIKE ? OR c.description LIKE ?
            GROUP BY c.id
            ORDER BY c.title
            LIMIT ?
        """, (pattern, pattern, limit)).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        tid_str = d.pop('topic_id_list', None)
        d['topic_ids'] = [int(x) for x in tid_str.split(',')] if tid_str else []
        results.append(d)
    return results


# ============================================================================
# Concept Detail (for fetch loop)
# ============================================================================

def get_concept_detail(concept_id: int) -> Optional[Dict]:
    """Get full concept detail: all fields + all remarks + last 5 reviews.
    This is the 'deep dive' query used by the fetch loop."""
    concept = get_concept(concept_id)
    if not concept:
        return None

    conn = _conn()

    remarks = conn.execute("""
        SELECT id, content, created_at FROM concept_remarks
        WHERE concept_id = ? ORDER BY id DESC LIMIT 10
    """, (concept_id,)).fetchall()
    concept['remarks'] = [dict(r) for r in remarks]

    reviews = conn.execute("""
        SELECT id, question_asked, user_response, quality, llm_assessment, reviewed_at
        FROM review_log
        WHERE concept_id = ? ORDER BY id DESC LIMIT 5
    """, (concept_id,)).fetchall()
    concept['recent_reviews'] = [dict(r) for r in reviews]

    topics = conn.execute("""
        SELECT t.id, t.title FROM topics t
        JOIN concept_topics ct ON t.id = ct.topic_id
        WHERE ct.concept_id = ?
    """, (concept_id,)).fetchall()
    concept['topics'] = [dict(t) for t in topics]

    conn.close()
    return concept
