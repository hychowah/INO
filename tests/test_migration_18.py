"""Tests for Migration 18: user-scoped concept title uniqueness."""

import sqlite3
from unittest.mock import patch

import db
from db import core


def _create_pre_migration_18_db(knowledge_path):
    conn = sqlite3.connect(knowledge_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        INSERT INTO schema_version (version) VALUES (17);

        CREATE TABLE IF NOT EXISTS concepts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            mastery_level INTEGER DEFAULT 0,
            ease_factor REAL DEFAULT 2.5,
            interval_days INTEGER DEFAULT 1,
            next_review_at DATETIME,
            last_reviewed_at DATETIME,
            review_count INTEGER DEFAULT 0,
            user_id TEXT NOT NULL DEFAULT 'default',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_concepts_title_nocase
            ON concepts(title COLLATE NOCASE);
        """
    )
    conn.execute(
        "INSERT INTO concepts (title, description, user_id) VALUES (?, ?, ?)",
        ("Shared Title", "desc", "default"),
    )
    conn.commit()
    conn.close()


def _get_index_names(db_path, table):
    conn = sqlite3.connect(db_path)
    names = [row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()]
    conn.close()
    return names


def test_migration_18_replaces_global_title_index(tmp_path):
    knowledge = tmp_path / "knowledge.db"
    chat = tmp_path / "chat_history.db"

    _create_pre_migration_18_db(knowledge)
    sqlite3.connect(chat).close()

    with (
        patch.object(core, "KNOWLEDGE_DB", knowledge),
        patch.object(core, "CHAT_DB", chat),
    ):
        from db import migrations

        migrations._run_migrations()

    indexes = _get_index_names(knowledge, "concepts")
    assert "idx_concepts_title_nocase" not in indexes
    assert "idx_concepts_user_title_nocase" in indexes

    conn = sqlite3.connect(knowledge)
    conn.execute(
        "INSERT INTO concepts (title, description, user_id) VALUES (?, ?, ?)",
        ("Shared Title", "other", "user_b"),
    )
    conn.commit()
    conn.close()


def test_fresh_db_allows_same_title_for_different_users(test_db):
    concept_a = db.add_concept("Repeatable Title", user_id="user_a")
    concept_b = db.add_concept("Repeatable Title", user_id="user_b")

    assert concept_a != concept_b


def test_add_concept_still_deduplicates_within_same_user(test_db):
    concept_a = db.add_concept("Case Fold Title", user_id="same_user")
    concept_b = db.add_concept("case fold title", user_id="same_user")

    assert concept_a == concept_b