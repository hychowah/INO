"""
Review log and concept remarks operations.
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from db.core import _conn, _now_iso


# ============================================================================
# Concept Remarks
# ============================================================================

# Maximum length for the remark_summary cache column
REMARK_SUMMARY_MAX = 4000


def add_remark(concept_id: int, content: str) -> int:
    """Add a remark to a concept. Also updates the remark_summary cache.
    The content is the full replacement summary (LLM-produced).
    Returns the remark ID."""
    now = _now_iso()
    conn = _conn()
    # Append-only row in concept_remarks (source of truth)
    cursor = conn.execute(
        "INSERT INTO concept_remarks (concept_id, content, created_at) VALUES (?, ?, ?)",
        (concept_id, content, now)
    )
    remark_id = cursor.lastrowid

    # Update summary cache on concepts table
    summary = content
    if len(summary) > REMARK_SUMMARY_MAX:
        summary = summary[:REMARK_SUMMARY_MAX - 15] + "\n…[truncated]"
    conn.execute(
        "UPDATE concepts SET remark_summary = ?, remark_updated_at = ? WHERE id = ?",
        (summary, now, concept_id)
    )
    conn.commit()
    conn.close()
    return remark_id


def get_remarks(concept_id: int, limit: int = 10) -> List[Dict]:
    """Get remarks for a concept, newest first."""
    conn = _conn()
    rows = conn.execute("""
        SELECT id, concept_id, content, created_at FROM concept_remarks
        WHERE concept_id = ? ORDER BY id DESC LIMIT ?
    """, (concept_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_remark(concept_id: int) -> Optional[str]:
    """Get the remark summary for a concept (cached on concepts table)."""
    conn = _conn()
    row = conn.execute(
        "SELECT remark_summary FROM concepts WHERE id = ?",
        (concept_id,)
    ).fetchone()
    conn.close()
    return row['remark_summary'] if row else None


# ============================================================================
# Review Log
# ============================================================================

def add_review(concept_id: int, question_asked: str, user_response: str,
               quality: int, llm_assessment: str) -> int:
    """Log a review/quiz result. Returns the review ID."""
    conn = _conn()
    cursor = conn.execute(
        """INSERT INTO review_log
           (concept_id, question_asked, user_response, quality, llm_assessment, reviewed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (concept_id, question_asked, user_response, quality, llm_assessment, _now_iso())
    )
    review_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return review_id


def get_recent_reviews(concept_id: int, limit: int = 5) -> List[Dict]:
    """Get recent review log entries for a concept."""
    conn = _conn()
    rows = conn.execute("""
        SELECT * FROM review_log
        WHERE concept_id = ? ORDER BY id DESC LIMIT ?
    """, (concept_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_review_stats() -> Dict[str, Any]:
    """Get aggregate review statistics."""
    conn = _conn()

    total_concepts = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    total_reviews = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]
    due_now = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE next_review_at IS NOT NULL AND next_review_at <= ?",
        (_now_iso(),)
    ).fetchone()[0]

    avg_row = conn.execute("SELECT AVG(mastery_level) as avg FROM concepts").fetchone()
    avg_mastery = round(avg_row['avg'], 1) if avg_row['avg'] is not None else 0.0

    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    recent_count = conn.execute(
        "SELECT COUNT(*) FROM review_log WHERE reviewed_at >= ?", (week_ago,)
    ).fetchone()[0]

    conn.close()
    return {
        'total_concepts': total_concepts,
        'total_reviews': total_reviews,
        'due_now': due_now,
        'avg_mastery': avg_mastery,
        'reviews_last_7d': recent_count,
    }
