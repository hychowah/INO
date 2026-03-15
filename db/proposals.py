"""
Pending proposals — DB-backed storage for dedup/maintenance proposals
awaiting user confirmation via Discord buttons.

Survives bot restarts. Auto-expires after 24h (configurable).
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta

from db.core import KNOWLEDGE_DB, _conn, _connection, _now_iso

logger = logging.getLogger("db.proposals")

# Default expiry: 24 hours
DEFAULT_EXPIRY_HOURS = 24


def save_proposal(proposal_type: str, payload: list[dict],
                  discord_message_id: int | None = None,
                  expiry_hours: int = DEFAULT_EXPIRY_HOURS) -> int:
    """Save a pending proposal to DB. Returns the proposal ID.

    Args:
        proposal_type: 'dedup' or 'maintenance'
        payload: list of action dicts (JSON-serializable)
        discord_message_id: Discord message ID for button views
        expiry_hours: hours until auto-expiry
    """
    expires_at = (datetime.now() + timedelta(hours=expiry_hours)).strftime('%Y-%m-%d %H:%M:%S')
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO pending_proposals (proposal_type, payload, discord_message_id, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (proposal_type, json.dumps(payload), discord_message_id, expires_at)
        )
        proposal_id = cursor.lastrowid
    logger.info(f"Saved {proposal_type} proposal #{proposal_id} ({len(payload)} groups, expires {expires_at})")
    return proposal_id


def get_proposal(proposal_id: int) -> dict | None:
    """Get a pending proposal by ID. Returns None if not found or expired."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, proposal_type, payload, discord_message_id, created_at, expires_at "
            "FROM pending_proposals WHERE id = ?",
            (proposal_id,)
        ).fetchone()
        if not row:
            return None
        # Check expiry
        expires_at = datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() > expires_at:
            # Expired — clean up
            conn.execute("DELETE FROM pending_proposals WHERE id = ?", (proposal_id,))
            conn.commit()
            return None
        return {
            'id': row['id'],
            'proposal_type': row['proposal_type'],
            'payload': json.loads(row['payload']),
            'discord_message_id': row['discord_message_id'],
            'created_at': row['created_at'],
            'expires_at': row['expires_at'],
        }
    finally:
        conn.close()


def get_pending_proposal(proposal_type: str) -> dict | None:
    """Get the latest non-expired pending proposal of a given type.
    Returns None if no pending proposal exists."""
    conn = _conn()
    now = _now_iso()
    try:
        row = conn.execute(
            "SELECT id, proposal_type, payload, discord_message_id, created_at, expires_at "
            "FROM pending_proposals WHERE proposal_type = ? AND expires_at > ? "
            "ORDER BY created_at DESC LIMIT 1",
            (proposal_type, now)
        ).fetchone()
        if not row:
            return None
        return {
            'id': row['id'],
            'proposal_type': row['proposal_type'],
            'payload': json.loads(row['payload']),
            'discord_message_id': row['discord_message_id'],
            'created_at': row['created_at'],
            'expires_at': row['expires_at'],
        }
    finally:
        conn.close()


def update_proposal_message_id(proposal_id: int, discord_message_id: int):
    """Update the Discord message ID after sending the proposal DM."""
    with _connection() as conn:
        conn.execute(
            "UPDATE pending_proposals SET discord_message_id = ? WHERE id = ?",
            (discord_message_id, proposal_id)
        )


def delete_proposal(proposal_id: int):
    """Delete a proposal (after execution or rejection)."""
    with _connection() as conn:
        conn.execute("DELETE FROM pending_proposals WHERE id = ?", (proposal_id,))
    logger.info(f"Deleted proposal #{proposal_id}")


def cleanup_expired():
    """Remove all expired proposals. Called periodically by scheduler."""
    now = _now_iso()
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM pending_proposals WHERE expires_at <= ?", (now,)
        )
        if cursor.rowcount > 0:
            logger.info(f"Cleaned up {cursor.rowcount} expired proposal(s)")
