"""Tests for Migration 17: user-scoped pending_proposals."""

import sqlite3
from unittest.mock import patch

import db
from db import core


def _create_pre_migration_17_db(knowledge_path):
    conn = sqlite3.connect(knowledge_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        INSERT INTO schema_version (version) VALUES (16);

        CREATE TABLE IF NOT EXISTS pending_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            discord_message_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO pending_proposals (proposal_type, payload, discord_message_id, expires_at) VALUES (?, ?, ?, ?)",
        ("maintenance", "[]", 123, "2099-01-01 00:00:00"),
    )
    conn.commit()
    conn.close()


def _get_table_columns(db_path, table):
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    conn.close()
    return cols


def test_migration_17_adds_user_id_to_pending_proposals(tmp_path):
    knowledge = tmp_path / "knowledge.db"
    chat = tmp_path / "chat_history.db"

    _create_pre_migration_17_db(knowledge)
    sqlite3.connect(chat).close()

    with (
        patch.object(core, "KNOWLEDGE_DB", knowledge),
        patch.object(core, "CHAT_DB", chat),
    ):
        from db import migrations

        migrations._run_migrations()

    cols = _get_table_columns(knowledge, "pending_proposals")
    assert "user_id" in cols

    conn = sqlite3.connect(knowledge)
    row = conn.execute("SELECT user_id, proposal_type, discord_message_id FROM pending_proposals").fetchone()
    conn.close()
    assert row == ("default", "maintenance", 123)


def test_fresh_db_has_user_scoped_pending_proposals(test_db):
    cols = _get_table_columns(db.core.KNOWLEDGE_DB, "pending_proposals")
    assert "user_id" in cols
