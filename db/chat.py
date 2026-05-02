"""
Chat history and session state operations.
"""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import db.core as db_core
from db.core import (
    CHAT_CLEANUP_DAYS,
    CLEANUP_THROTTLE_SECONDS,
    MAX_CHAT_HISTORY,
    _now_iso,
    _parse_datetime,
    _uid,
)

# In-memory cleanup throttle
_last_cleanup_time: float = 0.0
# Optional per-module override retained for tests that patch db.chat.CHAT_DB.
CHAT_DB = None


def _chat_db_path():
    return CHAT_DB or db_core.CHAT_DB


# ============================================================================
# Chat History
# ============================================================================


def add_chat_message(
    role: str, content: str, session_id: str = "learn", *, user_id: Optional[str] = None
):
    """Add a message to chat history and trigger cleanup."""
    uid = user_id or _uid()
    conn = sqlite3.connect(_chat_db_path())
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
    conn = sqlite3.connect(_chat_db_path())
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
    conn = sqlite3.connect(_chat_db_path())
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
    conn = sqlite3.connect(_chat_db_path())
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
    conn = sqlite3.connect(_chat_db_path())
    row = conn.execute(
        "SELECT value FROM session_state WHERE key = ? AND user_id = ?", (key, uid)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_session_updated_at(key: str, *, user_id: Optional[str] = None) -> Optional[str]:
    """Get the updated_at timestamp for a session state key, or None."""
    uid = user_id or _uid()
    conn = sqlite3.connect(_chat_db_path())
    row = conn.execute(
        "SELECT updated_at FROM session_state WHERE key = ? AND user_id = ?", (key, uid)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def clear_session(*, user_id: Optional[str] = None):
    """Clear session state. If user_id is given, clear only that user's keys."""
    conn = sqlite3.connect(_chat_db_path())
    if user_id is None:
        conn.execute("DELETE FROM session_state")
    else:
        conn.execute("DELETE FROM session_state WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def try_acquire_session_lease(
    key: str,
    owner_token: str,
    lease_seconds: int,
    *,
    user_id: Optional[str] = None,
    now: Optional[str] = None,
) -> bool:
    """Acquire or steal a session lease if it is missing or expired."""
    uid = user_id or _uid()
    now_value = now or _now_iso()
    now_dt = _parse_datetime(now_value) or datetime.now()
    expires_at = (now_dt + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S.%f")
    payload = json.dumps({"owner_token": owner_token, "expires_at": expires_at})

    conn = sqlite3.connect(_chat_db_path(), timeout=0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM session_state WHERE user_id = ? AND key = ?", (uid, key)
        ).fetchone()
        if row:
            current = _parse_session_lease_value(row[0])
            if current:
                current_expires_at = _parse_datetime(current.get("expires_at"))
                same_owner = current.get("owner_token") == owner_token
                if not same_owner and current_expires_at and current_expires_at > now_dt:
                    conn.rollback()
                    return False

        conn.execute(
            (
                "INSERT INTO session_state "
                "(user_id, key, value, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at"
            ),
            (uid, key, payload),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        conn.rollback()
        return False
    finally:
        conn.close()


def release_session_lease(key: str, owner_token: str, *, user_id: Optional[str] = None) -> bool:
    """Release a session lease if it is still owned by the given token."""
    uid = user_id or _uid()
    conn = sqlite3.connect(_chat_db_path(), timeout=0, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM session_state WHERE user_id = ? AND key = ?", (uid, key)
        ).fetchone()
        if not row:
            conn.rollback()
            return False

        current = _parse_session_lease_value(row[0])
        if not current or current.get("owner_token") != owner_token:
            conn.rollback()
            return False

        cursor = conn.execute(
            "DELETE FROM session_state WHERE user_id = ? AND key = ?", (uid, key)
        )
        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.OperationalError:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_session_lease(key: str, *, user_id: Optional[str] = None) -> Optional[dict]:
    """Return the parsed session lease payload for a key, if present."""
    raw = get_session(key, user_id=user_id)
    return _parse_session_lease_value(raw)


def _parse_session_lease_value(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _cleanup_chat_history(session_id: str = "learn"):
    """Keep max N messages and delete entries older than CHAT_CLEANUP_DAYS.
    Throttled to run at most once every CLEANUP_THROTTLE_SECONDS."""
    global _last_cleanup_time
    now = time.monotonic()
    if now - _last_cleanup_time < CLEANUP_THROTTLE_SECONDS:
        return
    _last_cleanup_time = now

    conn = sqlite3.connect(_chat_db_path())

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
