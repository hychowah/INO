"""Tests for Migration 12: session_state composite PK (user_id, key)."""

import sqlite3
from unittest.mock import patch

import db
from db import core
from services import state


def _create_old_schema_chat_db(chat_path):
    """Create a chat DB with the pre-migration-12 session_state schema."""
    conn = sqlite3.connect(chat_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT 'learn',
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS session_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def _insert_old_session_rows(chat_path, rows):
    """Insert rows into old-format session_state: [(key, value), ...]."""
    conn = sqlite3.connect(chat_path)
    for key, value in rows:
        conn.execute(
            "INSERT INTO session_state (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()


def _get_table_columns(db_path, table):
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    conn.close()
    return cols


def _get_table_pk(db_path, table):
    """Return list of column names that form the primary key."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(f"PRAGMA table_info({table})")
    pk_cols = [(row[1], row[5]) for row in cursor.fetchall() if row[5] > 0]
    conn.close()
    return [name for name, _ in sorted(pk_cols, key=lambda x: x[1])]


class TestMigration12:
    """Test migration 12: session_state old schema -> composite PK (user_id, key)."""

    def test_migration_converts_old_schema(self, tmp_path):
        """Old single-PK session_state is migrated to composite PK with user_id='default'."""
        knowledge = tmp_path / "knowledge.db"
        chat = tmp_path / "chat_history.db"

        # Create a knowledge DB with schema_version = 11
        conn = sqlite3.connect(knowledge)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (11);
        """)
        conn.commit()
        conn.close()

        # Create old chat DB and insert test data
        _create_old_schema_chat_db(chat)
        _insert_old_session_rows(
            chat,
            [
                ("active_concept_id", "42"),
                ("quiz_anchor_concept_id", "7"),
                ("persona", "buddy"),
            ],
        )

        # Run migration
        with (
            patch.object(core, "KNOWLEDGE_DB", knowledge),
            patch.object(core, "CHAT_DB", chat),
        ):
            from db import migrations

            migrations._run_migrations()

        # Verify schema
        cols = _get_table_columns(chat, "session_state")
        assert "user_id" in cols
        assert "key" in cols
        pk = _get_table_pk(chat, "session_state")
        assert pk == ["user_id", "key"]

        # Verify data preserved with user_id='default'
        conn = sqlite3.connect(chat)
        rows = conn.execute("SELECT user_id, key, value FROM session_state ORDER BY key").fetchall()
        conn.close()
        assert len(rows) == 3
        for user_id, _key, _value in rows:
            assert user_id == "default"
        keys = {r[1]: r[2] for r in rows}
        assert keys["active_concept_id"] == "42"
        assert keys["quiz_anchor_concept_id"] == "7"
        assert keys["persona"] == "buddy"

    def test_migration_idempotent(self, tmp_path):
        """Running migration 12 twice doesn't fail (has_column guard)."""
        knowledge = tmp_path / "knowledge.db"
        chat = tmp_path / "chat_history.db"

        conn = sqlite3.connect(knowledge)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (11);
        """)
        conn.commit()
        conn.close()

        _create_old_schema_chat_db(chat)
        _insert_old_session_rows(chat, [("test_key", "test_val")])

        with (
            patch.object(core, "KNOWLEDGE_DB", knowledge),
            patch.object(core, "CHAT_DB", chat),
        ):
            from db import migrations

            # First run
            migrations._run_migrations()
            # Reset version so migration block runs again
            core._set_schema_version(11)
            # Second run — should not fail
            migrations._run_migrations()

        # Still has correct data
        conn = sqlite3.connect(chat)
        rows = conn.execute("SELECT user_id, key, value FROM session_state").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0] == ("default", "test_key", "test_val")

    def test_fresh_db_has_composite_pk(self, test_db):
        """A freshly-initialized DB has the new session_state schema."""
        cols = _get_table_columns(db.chat.CHAT_DB, "session_state")
        assert "user_id" in cols
        pk = _get_table_pk(db.chat.CHAT_DB, "session_state")
        assert pk == ["user_id", "key"]

    def test_helpers_round_trip_default_user(self, test_db):
        """set_session/get_session work with default user_id."""
        db.set_session("test_key", "test_value")
        assert db.get_session("test_key") == "test_value"

        db.set_session("test_key", None)
        assert db.get_session("test_key") is None

    def test_helpers_round_trip_explicit_user(self, test_db):
        """set_session/get_session with explicit user_id isolates data."""
        db.set_session("shared_key", "val_a", user_id="user_a")
        db.set_session("shared_key", "val_b", user_id="user_b")

        assert db.get_session("shared_key", user_id="user_a") == "val_a"
        assert db.get_session("shared_key", user_id="user_b") == "val_b"
        # Default user doesn't see either
        assert db.get_session("shared_key") is None

    def test_helpers_resolve_context_user_by_default(self, test_db):
        """Omitted user_id uses the current ContextVar-backed user."""
        previous_user = state.get_current_user()
        state.set_current_user("ctx_user")
        try:
            db.set_session("ctx_key", "ctx_value")
            assert db.get_session("ctx_key") == "ctx_value"
            assert db.get_session("ctx_key", user_id="default") is None
        finally:
            state.set_current_user(previous_user)

    def test_get_session_updated_at_with_user(self, test_db):
        """get_session_updated_at respects user_id scoping."""
        db.set_session("ts_key", "v1", user_id="user_x")
        ts = db.get_session_updated_at("ts_key", user_id="user_x")
        assert ts is not None
        assert db.get_session_updated_at("ts_key") is None

    def test_clear_session_all_users(self, test_db):
        """clear_session() with no args clears all users."""
        db.set_session("k1", "v1", user_id="user_a")
        db.set_session("k2", "v2", user_id="user_b")
        db.set_session("k3", "v3")
        db.clear_session()
        assert db.get_session("k1", user_id="user_a") is None
        assert db.get_session("k2", user_id="user_b") is None
        assert db.get_session("k3") is None

    def test_clear_session_specific_user(self, test_db):
        """clear_session(user_id=...) only clears that user."""
        db.set_session("key", "val_a", user_id="user_a")
        db.set_session("key", "val_b", user_id="user_b")
        db.clear_session(user_id="user_a")
        assert db.get_session("key", user_id="user_a") is None
        assert db.get_session("key", user_id="user_b") == "val_b"
