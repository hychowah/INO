"""
Pending proposals — DB-backed storage for dedup/maintenance proposals
awaiting user confirmation via Discord buttons.

Survives bot restarts. Auto-expires after 24h (configurable).
"""

import json
import logging
from datetime import datetime, timedelta

from db.core import _conn, _connection, _now_iso, _uid

logger = logging.getLogger("db.proposals")

# Default expiry: 24 hours
DEFAULT_EXPIRY_HOURS = 24


def save_proposal(
    proposal_type: str,
    payload: list[dict],
    discord_message_id: int | None = None,
    expiry_hours: int = DEFAULT_EXPIRY_HOURS,
    *,
    user_id: str | None = None,
) -> int:
    """Save a pending proposal to DB. Returns the proposal ID.

    Args:
        proposal_type: 'dedup' or 'maintenance'
        payload: list of action dicts (JSON-serializable)
        discord_message_id: Discord message ID for button views
        expiry_hours: hours until auto-expiry
    """
    uid = user_id or _uid()
    expires_at = (datetime.now() + timedelta(hours=expiry_hours)).strftime("%Y-%m-%d %H:%M:%S")
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO pending_proposals "
            "(user_id, proposal_type, payload, discord_message_id, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (uid, proposal_type, json.dumps(payload), discord_message_id, expires_at),
        )
        proposal_id = cursor.lastrowid
    logger.info(
        f"Saved {proposal_type} proposal #{proposal_id} for user {uid} "
        f"({len(payload)} groups, expires {expires_at})"
    )
    return proposal_id


def get_proposal(proposal_id: int, *, user_id: str | None = None) -> dict | None:
    """Get a pending proposal by ID. Returns None if not found or expired."""
    uid = user_id or _uid()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, user_id, proposal_type, payload, discord_message_id, created_at, expires_at "
            "FROM pending_proposals WHERE id = ? AND user_id = ?",
            (proposal_id, uid),
        ).fetchone()
        if not row:
            return None
        # Check expiry
        expires_at = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expires_at:
            # Expired — clean up
            conn.execute("DELETE FROM pending_proposals WHERE id = ? AND user_id = ?", (proposal_id, uid))
            conn.commit()
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "proposal_type": row["proposal_type"],
            "payload": json.loads(row["payload"]),
            "discord_message_id": row["discord_message_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
    finally:
        conn.close()


def get_pending_proposal(proposal_type: str, *, user_id: str | None = None) -> dict | None:
    """Get the latest non-expired pending proposal of a given type.
    Returns None if no pending proposal exists."""
    uid = user_id or _uid()
    conn = _conn()
    now = _now_iso()
    try:
        row = conn.execute(
            "SELECT id, user_id, proposal_type, payload, discord_message_id, created_at, expires_at "
            "FROM pending_proposals WHERE user_id = ? AND proposal_type = ? AND expires_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (uid, proposal_type, now),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "proposal_type": row["proposal_type"],
            "payload": json.loads(row["payload"]),
            "discord_message_id": row["discord_message_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }
    finally:
        conn.close()


def update_proposal_message_id(
    proposal_id: int, discord_message_id: int, *, user_id: str | None = None
):
    """Update the Discord message ID after sending the proposal DM."""
    uid = user_id or _uid()
    with _connection() as conn:
        conn.execute(
            "UPDATE pending_proposals SET discord_message_id = ? WHERE id = ? AND user_id = ?",
            (discord_message_id, proposal_id, uid),
        )


def delete_proposal(proposal_id: int, *, user_id: str | None = None):
    """Delete a proposal (after execution or rejection)."""
    uid = user_id or _uid()
    with _connection() as conn:
        conn.execute("DELETE FROM pending_proposals WHERE id = ? AND user_id = ?", (proposal_id, uid))
    logger.info(f"Deleted proposal #{proposal_id} for user {uid}")


def cleanup_expired():
    """Remove all expired proposals. Called periodically by scheduler."""
    now = _now_iso()
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM pending_proposals WHERE expires_at <= ?", (now,))
        if cursor.rowcount > 0:
            logger.info(f"Cleaned up {cursor.rowcount} expired proposal(s)")
