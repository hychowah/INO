"""
Chat history and session state operations.
"""

import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from db.core import (
    CHAT_CLEANUP_DAYS,
    CHAT_DB,
    CLEANUP_THROTTLE_SECONDS,
    MAX_CHAT_HISTORY,
    _now_iso,
    _uid,
)

# In-memory cleanup throttle
_last_cleanup_time: float = 0.0


# ============================================================================
# Chat History
# ============================================================================


def add_chat_message(
    role: str, content: str, session_id: str = "learn", *, user_id: Optional[str] = None
):
    """Add a message to chat history and trigger cleanup."""
    uid = user_id or _uid()
    conn = sqlite3.connect(CHAT_DB)
    conn.execute(
        (
            "INSERT INTO conversations "
            "(session_id, role, content, timestamp, user_id) "
            "VALUES (?, ?, ?, ?, ?)"
        ),
        (session_id, role, content, _now_iso(), uid),
    )
    conn.commit()
    conn.close()
    _cleanup_chat_history(session_id)


def get_chat_history(
    limit: int = 10, session_id: str = "learn", *, user_id: Optional[str] = None
) -> List[Dict]:
    """Get recent chat history, oldest first."""
    uid = user_id or _uid()
    conn = sqlite3.connect(CHAT_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT role, content, timestamp FROM conversations
        WHERE session_id = ? AND user_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
    """,
        (session_id, uid, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def clear_chat_history(session_id: str = "learn", *, user_id: Optional[str] = None):
    """Clear all chat history for a session."""
    uid = user_id or _uid()
    conn = sqlite3.connect(CHAT_DB)
    conn.execute(
        "DELETE FROM conversations WHERE session_id = ? AND user_id = ?", (session_id, uid)
    )
    conn.commit()
    conn.close()


# ============================================================================
# Session State (lightweight key-value store for cross-turn context)
# ============================================================================


def set_session(key: str, value: Optional[str], *, user_id: Optional[str] = None):
    """Set a session state key. Pass None to delete."""
    uid = user_id or _uid()
    conn = sqlite3.connect(CHAT_DB)
    if value is None:
        conn.execute("DELETE FROM session_state WHERE key = ? AND user_id = ?", (key, uid))
    else:
        conn.execute(
            (
                "INSERT INTO session_state "
                "(user_id, key, value, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at"
            ),
            (uid, key, value),
        )
    conn.commit()
    conn.close()


def get_session(key: str, *, user_id: Optional[str] = None) -> Optional[str]:
    """Get a session state value, or None if not set."""
    uid = user_id or _uid()
    conn = sqlite3.connect(CHAT_DB)
    row = conn.execute(
        "SELECT value FROM session_state WHERE key = ? AND user_id = ?", (key, uid)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_session_updated_at(key: str, *, user_id: Optional[str] = None) -> Optional[str]:
    """Get the updated_at timestamp for a session state key, or None."""
    uid = user_id or _uid()
    conn = sqlite3.connect(CHAT_DB)
    row = conn.execute(
        "SELECT updated_at FROM session_state WHERE key = ? AND user_id = ?", (key, uid)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def clear_session(*, user_id: Optional[str] = None):
    """Clear session state. If user_id is given, clear only that user's keys."""
    conn = sqlite3.connect(CHAT_DB)
    if user_id is None:
        conn.execute("DELETE FROM session_state")
    else:
        conn.execute("DELETE FROM session_state WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def _cleanup_chat_history(session_id: str = "learn"):
    """Keep max N messages and delete entries older than CHAT_CLEANUP_DAYS.
    Throttled to run at most once every CLEANUP_THROTTLE_SECONDS."""
    global _last_cleanup_time
    now = time.monotonic()
    if now - _last_cleanup_time < CLEANUP_THROTTLE_SECONDS:
        return
    _last_cleanup_time = now

    conn = sqlite3.connect(CHAT_DB)

    cutoff = (datetime.now() - timedelta(days=CHAT_CLEANUP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "DELETE FROM conversations WHERE session_id = ? AND timestamp < ?", (session_id, cutoff)
    )

    conn.execute(
        """
        DELETE FROM conversations WHERE session_id = ? AND id NOT IN (
            SELECT id FROM conversations
            WHERE session_id = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        )
    """,
        (session_id, session_id, MAX_CHAT_HISTORY),
    )

    conn.commit()
    conn.close()
