"""
Action log operations — audit trail for bot actions.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from db.core import _conn, _connection, _now_iso

logger = logging.getLogger("db.action_log")

# Maximum stored length for params and result fields
_MAX_PARAMS_LEN = 2000
_MAX_RESULT_LEN = 500


# ============================================================================
# Write
# ============================================================================


def log_action(
    action: str,
    params: Any,
    result_type: str,
    result: str,
    source: str = "discord",
    user_id: str = "default",
) -> int:
    """Insert an action log entry. Returns the log entry ID.

    params: dict or JSON string — will be serialized and truncated.
    result: truncated to _MAX_RESULT_LEN chars.
    """
    # Serialize params
    if isinstance(params, dict):
        params_str = json.dumps(params, default=str)
    elif params is not None:
        params_str = str(params)
    else:
        params_str = None

    # Truncate
    if params_str and len(params_str) > _MAX_PARAMS_LEN:
        params_str = params_str[: _MAX_PARAMS_LEN - 1] + "…"
    result_str = str(result) if result is not None else ""
    if len(result_str) > _MAX_RESULT_LEN:
        result_str = result_str[: _MAX_RESULT_LEN - 1] + "…"

    conn = _conn()
    cursor = conn.execute(
        """INSERT INTO action_log
           (action, params, result_type, result, source, user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (action, params_str, result_type, result_str, source, user_id, _now_iso()),
    )
    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return entry_id


# ============================================================================
# Read
# ============================================================================


def get_action_log(
    limit: int = 50,
    offset: int = 0,
    action_filter: Optional[str] = None,
    source_filter: Optional[str] = None,
    since: Optional[datetime] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query action log with optional filters, ordered by created_at DESC."""
    clauses: list[str] = []
    params: list[Any] = []

    if action_filter:
        clauses.append("action = ?")
        params.append(action_filter)
    if source_filter:
        clauses.append("source = ?")
        params.append(source_filter)
    if since:
        clauses.append("created_at >= ?")
        params.append(since.strftime("%Y-%m-%d %H:%M:%S"))
    if search:
        clauses.append("(action LIKE ? OR params LIKE ? OR result LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM action_log{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_action_log_count(
    action_filter: Optional[str] = None,
    source_filter: Optional[str] = None,
    since: Optional[datetime] = None,
    search: Optional[str] = None,
) -> int:
    """Count action log entries matching the given filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if action_filter:
        clauses.append("action = ?")
        params.append(action_filter)
    if source_filter:
        clauses.append("source = ?")
        params.append(source_filter)
    if since:
        clauses.append("created_at >= ?")
        params.append(since.strftime("%Y-%m-%d %H:%M:%S"))
    if search:
        clauses.append("(action LIKE ? OR params LIKE ? OR result LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT COUNT(*) FROM action_log{where}"

    conn = _conn()
    count = conn.execute(sql, params).fetchone()[0]
    conn.close()
    return count


def get_action_summary(days: int = 7) -> Dict[str, Any]:
    """Aggregate action counts by type for the last N days."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    today_start = datetime.now().replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S")

    conn = _conn()

    # Counts for the period
    rows = conn.execute(
        "SELECT action, COUNT(*) as cnt FROM action_log "
        "WHERE created_at >= ? GROUP BY action ORDER BY cnt DESC",
        (since,),
    ).fetchall()
    by_action = {r["action"]: r["cnt"] for r in rows}

    # Today's counts
    today_rows = conn.execute(
        "SELECT action, COUNT(*) as cnt FROM action_log "
        "WHERE created_at >= ? GROUP BY action ORDER BY cnt DESC",
        (today_start,),
    ).fetchall()
    today_by_action = {r["action"]: r["cnt"] for r in today_rows}

    # Total count
    total = conn.execute(
        "SELECT COUNT(*) FROM action_log WHERE created_at >= ?", (since,)
    ).fetchone()[0]
    today_total = conn.execute(
        "SELECT COUNT(*) FROM action_log WHERE created_at >= ?", (today_start,)
    ).fetchone()[0]

    conn.close()

    return {
        "days": days,
        "total": total,
        "today_total": today_total,
        "by_action": by_action,
        "today_by_action": today_by_action,
    }


def get_distinct_actions() -> List[str]:
    """Return distinct action names present in the log."""
    conn = _conn()
    rows = conn.execute("SELECT DISTINCT action FROM action_log ORDER BY action").fetchall()
    conn.close()
    return [r["action"] for r in rows]


def get_distinct_sources() -> List[str]:
    """Return distinct source values present in the log."""
    conn = _conn()
    rows = conn.execute("SELECT DISTINCT source FROM action_log ORDER BY source").fetchall()
    conn.close()
    return [r["source"] for r in rows]


# ============================================================================
# Cleanup
# ============================================================================


def cleanup_old_actions(days: int = 90) -> int:
    """Delete action log entries older than N days. Returns count deleted."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM action_log WHERE created_at < ?", (cutoff,))
        deleted = cursor.rowcount
    if deleted:
        logger.info(f"Cleaned up {deleted} action log entries older than {days} days")
    return deleted
