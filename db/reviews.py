"""
Review log and concept remarks operations.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from db.core import _conn, _now_iso, _uid

# ============================================================================
# Concept Remarks
# ============================================================================

# Maximum length for the remark_summary cache column
REMARK_SUMMARY_MAX = 4000


def add_remark(concept_id: int, content: str, *, user_id: Optional[str] = None) -> int:
    """Add a remark to a concept. Also updates the remark_summary cache.
    The content is the full replacement summary (LLM-produced).
    Returns the remark ID."""
    uid = user_id or _uid()
    now = _now_iso()
    conn = _conn()
    # Append-only row in concept_remarks (source of truth)
    cursor = conn.execute(
        "INSERT INTO concept_remarks (concept_id, content, created_at, user_id) VALUES (?, ?, ?, ?)",
        (concept_id, content, now, uid),
    )
    remark_id = cursor.lastrowid

    # Update summary cache on concepts table
    summary = content
    if len(summary) > REMARK_SUMMARY_MAX:
        summary = summary[: REMARK_SUMMARY_MAX - 15] + "\n…[truncated]"
    conn.execute(
        "UPDATE concepts SET remark_summary = ?, remark_updated_at = ? WHERE id = ?",
        (summary, now, concept_id),
    )
    conn.commit()
    conn.close()
    return remark_id


def get_remarks(concept_id: int, limit: int = 10, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get remarks for a concept, newest first."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        """
        SELECT id, concept_id, content, created_at FROM concept_remarks
        WHERE concept_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?
    """,
        (concept_id, uid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_remark(concept_id: int, *, user_id: Optional[str] = None) -> Optional[str]:
    """Get the remark summary for a concept (cached on concepts table)."""
    uid = user_id or _uid()
    conn = _conn()
    row = conn.execute("SELECT remark_summary FROM concepts WHERE id = ? AND user_id = ?", (concept_id, uid)).fetchone()
    conn.close()
    return row["remark_summary"] if row else None


# ============================================================================
# Review Log
# ============================================================================


def add_review(
    concept_id: int, question_asked: str, user_response: str, quality: int, llm_assessment: str,
    *, user_id: Optional[str] = None,
) -> int:
    """Log a review/quiz result. Returns the review ID."""
    uid = user_id or _uid()
    conn = _conn()
    cursor = conn.execute(
        """INSERT INTO review_log
           (concept_id, question_asked, user_response, quality, llm_assessment, reviewed_at, user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (concept_id, question_asked, user_response, quality, llm_assessment, _now_iso(), uid),
    )
    review_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return review_id


def get_recent_reviews(concept_id: int, limit: int = 5, *, user_id: Optional[str] = None) -> List[Dict]:
    """Get recent review log entries for a concept."""
    uid = user_id or _uid()
    conn = _conn()
    rows = conn.execute(
        """
        SELECT * FROM review_log
        WHERE concept_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?
    """,
        (concept_id, uid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_review_stats(*, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Get aggregate review statistics."""
    uid = user_id or _uid()
    conn = _conn()

    total_concepts = conn.execute("SELECT COUNT(*) FROM concepts WHERE user_id = ?", (uid,)).fetchone()[0]
    total_reviews = conn.execute("SELECT COUNT(*) FROM review_log WHERE user_id = ?", (uid,)).fetchone()[0]
    due_now = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE next_review_at IS NOT NULL AND next_review_at <= ? AND user_id = ?",
        (_now_iso(), uid),
    ).fetchone()[0]

    avg_row = conn.execute("SELECT AVG(mastery_level) as avg FROM concepts WHERE user_id = ?", (uid,)).fetchone()
    avg_mastery = round(avg_row["avg"], 1) if avg_row["avg"] is not None else 0.0

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    recent_count = conn.execute(
        "SELECT COUNT(*) FROM review_log WHERE reviewed_at >= ? AND user_id = ?", (week_ago, uid)
    ).fetchone()[0]

    conn.close()
    return {
        "total_concepts": total_concepts,
        "total_reviews": total_reviews,
        "due_now": due_now,
        "avg_mastery": avg_mastery,
        "reviews_last_7d": recent_count,
    }
