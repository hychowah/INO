"""
Database migrations — all schema migration blocks extracted from core.py.

TO ADD A NEW MIGRATION:
1. Bump SCHEMA_VERSION in db/core.py
2. Add an `if current < N:` block in _run_migrations() below
3. Use _has_column() before ALTER TABLE to stay safe
"""

import math
import sqlite3
from datetime import datetime, timedelta

import db.core as _core


def _run_migrations():
    """Run all pending migrations. Each migration is idempotent."""
    # Access constants via module reference so test patches are respected
    KNOWLEDGE_DB = _core.KNOWLEDGE_DB
    CHAT_DB = _core.CHAT_DB
    SCHEMA_VERSION = _core.SCHEMA_VERSION

    current = _core._get_schema_version()
    if current >= SCHEMA_VERSION:
        return

    # --- Migration 1: base schema (created in _init_knowledge_db) ---
    if current < 1:
        pass  # All tables created in _init_knowledge_db

    # --- Migration 2: FTS5 virtual tables for full-text search ---
    if current < 2:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS concepts_fts USING fts5(
                title, description, content='concepts', content_rowid='id'
            );

            -- Populate from existing data
            INSERT OR IGNORE INTO concepts_fts(rowid, title, description)
            SELECT id, title, COALESCE(description, '') FROM concepts;

            -- Keep FTS in sync via triggers
            CREATE TRIGGER IF NOT EXISTS concepts_fts_insert AFTER INSERT ON concepts BEGIN
                INSERT INTO concepts_fts(rowid, title, description)
                VALUES (new.id, new.title, COALESCE(new.description, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS concepts_fts_delete AFTER DELETE ON concepts BEGIN
                INSERT INTO concepts_fts(concepts_fts, rowid, title, description)
                VALUES ('delete', old.id, old.title, COALESCE(old.description, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS concepts_fts_update AFTER UPDATE ON concepts BEGIN
                INSERT INTO concepts_fts(concepts_fts, rowid, title, description)
                VALUES ('delete', old.id, old.title, COALESCE(old.description, ''));
                INSERT INTO concepts_fts(rowid, title, description)
                VALUES (new.id, new.title, COALESCE(new.description, ''));
            END;

            -- FTS5 for topics
            CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(
                title, description, content='topics', content_rowid='id'
            );

            INSERT OR IGNORE INTO topics_fts(rowid, title, description)
            SELECT id, title, COALESCE(description, '') FROM topics;

            CREATE TRIGGER IF NOT EXISTS topics_fts_insert AFTER INSERT ON topics BEGIN
                INSERT INTO topics_fts(rowid, title, description)
                VALUES (new.id, new.title, COALESCE(new.description, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS topics_fts_delete AFTER DELETE ON topics BEGIN
                INSERT INTO topics_fts(topics_fts, rowid, title, description)
                VALUES ('delete', old.id, old.title, COALESCE(old.description, ''));
            END;

            CREATE TRIGGER IF NOT EXISTS topics_fts_update AFTER UPDATE ON topics BEGIN
                INSERT INTO topics_fts(topics_fts, rowid, title, description)
                VALUES ('delete', old.id, old.title, COALESCE(old.description, ''));
                INSERT INTO topics_fts(rowid, title, description)
                VALUES (new.id, new.title, COALESCE(new.description, ''));
            END;
        """)
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 2: FTS5 virtual tables created")

    # --- Migration 3: Normalize datetime formats (strip timezone offsets) ---
    if current < 3:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        for col in ("next_review_at", "last_reviewed_at", "created_at", "updated_at"):
            rows = conn.execute(
                f"SELECT id, {col} FROM concepts WHERE {col} IS NOT NULL AND {col} LIKE '%+%'"
            ).fetchall()
            rows += conn.execute(
                f"SELECT id, {col} FROM concepts WHERE {col} IS NOT NULL AND {col} LIKE '%T%'"
            ).fetchall()
            seen = set()
            for row_id, val in rows:
                if row_id in seen:
                    continue
                seen.add(row_id)
                normalized = _core._normalize_dt_str(val)
                if normalized and normalized != val:
                    conn.execute(
                        f"UPDATE concepts SET {col} = ? WHERE id = ?", (normalized, row_id)
                    )
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 3: Normalized datetime formats")

    # --- Migration 4: Score-based review system (mastery 0–5 → score 0–100) ---
    if current < 4:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        max_score = conn.execute("SELECT MAX(mastery_level) FROM concepts").fetchone()[0]
        if max_score is not None and max_score <= 5:
            conn.execute("UPDATE concepts SET mastery_level = mastery_level * 15")
            rows = conn.execute("SELECT id, mastery_level FROM concepts").fetchall()
            for row_id, score in rows:
                new_interval = max(1, round(math.exp((score or 0) * 0.05)))
                conn.execute(
                    "UPDATE concepts SET interval_days = ? WHERE id = ?", (new_interval, row_id)
                )
            rows = conn.execute(
                "SELECT id, last_reviewed_at, interval_days FROM concepts "
                "WHERE last_reviewed_at IS NOT NULL"
            ).fetchall()
            for row_id, last_rev, interval in rows:
                try:
                    last_dt = datetime.strptime(last_rev, "%Y-%m-%d %H:%M:%S")
                    new_next = (last_dt + timedelta(days=interval)).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        "UPDATE concepts SET next_review_at = ? WHERE id = ?", (new_next, row_id)
                    )
                except (ValueError, TypeError):
                    pass
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 4: Score-based review system (0-100)")

    # --- Migration 5: Add user_id columns for multi-user prep ---
    if current < 5:
        # knowledge.db tables
        conn = sqlite3.connect(KNOWLEDGE_DB)
        for table in ("topics", "concepts", "review_log", "concept_remarks"):
            # Guard: table may have been renamed/dropped by a later migration
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if exists and not _core._has_column(table, "user_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT DEFAULT 'default'")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)")
        conn.commit()
        conn.close()

        # chat_history.db tables
        chat_conn = sqlite3.connect(CHAT_DB)
        if not _core._has_column("conversations", "user_id", db_path=CHAT_DB):
            chat_conn.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default'")
            chat_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)"
            )
        chat_conn.commit()
        chat_conn.close()
        print("[LEARN DB] Migration 5: Added user_id columns for multi-user prep")

    # --- Migration 6: pending_proposals table for confirmation flows ---
    if current < 6:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                discord_message_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL
            );
        """)
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 6: pending_proposals table")

    # --- Migration 7: action_log table for bot action audit trail ---
    if current < 7:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                params TEXT,
                result_type TEXT,
                result TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                user_id TEXT DEFAULT 'default',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_action_log_filter
                ON action_log(action, source, created_at);
        """)
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 7: action_log table")

    # --- Migration 8: UNIQUE index on concept titles (case-insensitive) ---
    if current < 8:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        # Clean up any existing exact-title duplicates before creating UNIQUE index.
        # Keeps the concept with the lowest ID (= the original) for each title.
        conn.execute("""
            DELETE FROM concepts
            WHERE id NOT IN (
                SELECT MIN(id) FROM concepts GROUP BY LOWER(title)
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_concepts_title_nocase
            ON concepts(title COLLATE NOCASE)
        """)
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 8: UNIQUE index on concept titles (dedup guard)")

    # --- Migration 9: concept_relations table for cross-concept edges ---
    if current < 9:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS concept_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept_id_low INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                concept_id_high INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL CHECK(relation_type IN
                    ('builds_on','contrasts_with','commonly_confused','applied_together','same_phenomenon')),
                note TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(concept_id_low, concept_id_high),
                CHECK(concept_id_low < concept_id_high)
            );
            CREATE INDEX IF NOT EXISTS idx_concept_relations_low
                ON concept_relations(concept_id_low);
            CREATE INDEX IF NOT EXISTS idx_concept_relations_high
                ON concept_relations(concept_id_high);
        """)
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 9: concept_relations table")

    # --- Migration 10: remark_summary cache column on concepts ---
    if current < 10:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        if not _core._has_column("concepts", "remark_summary"):
            conn.execute("ALTER TABLE concepts ADD COLUMN remark_summary TEXT")
        if not _core._has_column("concepts", "remark_updated_at"):
            conn.execute("ALTER TABLE concepts ADD COLUMN remark_updated_at DATETIME")

        # Populate cache from existing concept_remarks (newest-first, limit 5 per concept)
        concept_ids = conn.execute("SELECT DISTINCT concept_id FROM concept_remarks").fetchall()
        for (cid,) in concept_ids:
            rows = conn.execute(
                "SELECT content FROM concept_remarks WHERE concept_id = ? ORDER BY id DESC LIMIT 5",
                (cid,),
            ).fetchall()
            if rows:
                summary = "\n---\n".join(r[0] for r in rows)
                # Enforce 4000-char limit
                if len(summary) > 4000:
                    summary = summary[:3985] + "\n…[truncated]"
                max_ts = conn.execute(
                    "SELECT MAX(created_at) FROM concept_remarks WHERE concept_id = ?", (cid,)
                ).fetchone()[0]
                conn.execute(
                    "UPDATE concepts SET remark_summary = ?, remark_updated_at = ? WHERE id = ?",
                    (summary, max_ts, cid),
                )
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 10: remark_summary cache column on concepts")

    # --- Migration 11: last_quiz_generator_output cache column ---
    if current < 11:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        if not _core._has_column("concepts", "last_quiz_generator_output"):
            conn.execute("ALTER TABLE concepts ADD COLUMN last_quiz_generator_output TEXT")
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 11: last_quiz_generator_output column on concepts")

    # --- Migration 12: session_state composite PK (user_id, key) ---
    if current < 12:
        conn = sqlite3.connect(CHAT_DB)
        if not _core._has_column("session_state", "user_id", db_path=CHAT_DB):
            conn.executescript("""
                CREATE TABLE session_state_new (
                    user_id TEXT NOT NULL DEFAULT 'default',
                    key TEXT NOT NULL,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, key)
                );
                INSERT INTO session_state_new (user_id, key, value, updated_at)
                    SELECT 'default', key, value, updated_at FROM session_state;
                DROP TABLE session_state;
                ALTER TABLE session_state_new RENAME TO session_state;
            """)
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 12: session_state composite PK (user_id, key)")

    # --- Migration 13: users table for multi-user identity ---
    if current < 13:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT,
                discord_id TEXT UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO users (id, display_name) VALUES ('default', 'Default User')"
        )
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 13: users table")

    # --- Migration 14: structured quiz metadata on review_log ---
    if current < 14:
        conn = sqlite3.connect(KNOWLEDGE_DB)
        if _core._has_table("review_log"):
            if not _core._has_column("review_log", "question_type"):
                conn.execute("ALTER TABLE review_log ADD COLUMN question_type TEXT")
            if not _core._has_column("review_log", "target_facet"):
                conn.execute("ALTER TABLE review_log ADD COLUMN target_facet TEXT")
            if not _core._has_column("review_log", "question_difficulty"):
                conn.execute("ALTER TABLE review_log ADD COLUMN question_difficulty INTEGER")
        conn.commit()
        conn.close()
        print("[LEARN DB] Migration 14: review_log quiz metadata columns")

    _core._set_schema_version(SCHEMA_VERSION)
    print(f"[LEARN DB] Migrated schema to version {SCHEMA_VERSION}")
