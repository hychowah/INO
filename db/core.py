"""
Database core — connection helpers, initialization, and migrations.
"""

import math
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Database paths
DATA_DIR = Path(__file__).parent.parent / "data"
KNOWLEDGE_DB = DATA_DIR / "knowledge.db"
CHAT_DB = DATA_DIR / "chat_history.db"

# Configuration
MAX_CHAT_HISTORY = 100
CHAT_CLEANUP_DAYS = 7
CLEANUP_THROTTLE_SECONDS = 600  # only run cleanup every 10 minutes

# Schema version — bump this when adding migrations
SCHEMA_VERSION = 7


# ============================================================================
# Initialization & Migrations
# ============================================================================

def init_databases():
    """Initialize all databases with schema, then run migrations."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _init_knowledge_db()
    _init_chat_db()
    _run_migrations()


def _init_knowledge_db():
    """Create knowledge database schema."""
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topic_relations (
            parent_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            child_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(parent_id, child_id)
        );

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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS concept_topics (
            concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            UNIQUE(concept_id, topic_id)
        );

        CREATE TABLE IF NOT EXISTS concept_remarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS review_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            question_asked TEXT,
            user_response TEXT,
            quality INTEGER,
            llm_assessment TEXT,
            reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_concepts_next_review ON concepts(next_review_at);
        CREATE INDEX IF NOT EXISTS idx_concepts_mastery ON concepts(mastery_level);
        CREATE INDEX IF NOT EXISTS idx_concept_topics_concept ON concept_topics(concept_id);
        CREATE INDEX IF NOT EXISTS idx_concept_topics_topic ON concept_topics(topic_id);
        CREATE INDEX IF NOT EXISTS idx_topic_relations_parent ON topic_relations(parent_id);
        CREATE INDEX IF NOT EXISTS idx_topic_relations_child ON topic_relations(child_id);
        CREATE INDEX IF NOT EXISTS idx_remarks_concept ON concept_remarks(concept_id);
        CREATE INDEX IF NOT EXISTS idx_review_log_concept ON review_log(concept_id);
        CREATE INDEX IF NOT EXISTS idx_review_log_reviewed ON review_log(reviewed_at);

        CREATE TABLE IF NOT EXISTS pending_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            discord_message_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL
        );
    """)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()


def _init_chat_db():
    """Create chat history database schema."""
    conn = sqlite3.connect(CHAT_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT DEFAULT 'learn',
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_lookup
        ON conversations(session_id, timestamp DESC);

        -- TODO: Phase 3 — session_state PK is (key), needs user scoping
        -- (prefix keys with user_id or rebuild as composite PK)
        CREATE TABLE IF NOT EXISTS session_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def _get_schema_version() -> int:
    """Get current schema version from DB (0 if never set)."""
    conn = sqlite3.connect(KNOWLEDGE_DB)
    try:
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _set_schema_version(version: int):
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.execute("DELETE FROM schema_version")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()
    conn.close()


def _has_column(table: str, column: str, db_path=None) -> bool:
    """Check if a column exists in a table (safe for migrations).
    Uses KNOWLEDGE_DB by default; pass db_path for other databases."""
    conn = sqlite3.connect(db_path or KNOWLEDGE_DB)
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    return column in columns


def _run_migrations():
    """
    Run all pending migrations. Each migration is idempotent.

    TO ADD A NEW MIGRATION:
    1. Bump SCHEMA_VERSION at the top of this file
    2. Add an `if current < N:` block below
    3. Use _has_column() before ALTER TABLE to stay safe
    """
    current = _get_schema_version()
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
        for col in ('next_review_at', 'last_reviewed_at', 'created_at', 'updated_at'):
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
                normalized = _normalize_dt_str(val)
                if normalized and normalized != val:
                    conn.execute(
                        f"UPDATE concepts SET {col} = ? WHERE id = ?",
                        (normalized, row_id)
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
                    "UPDATE concepts SET interval_days = ? WHERE id = ?",
                    (new_interval, row_id)
                )
            rows = conn.execute(
                "SELECT id, last_reviewed_at, interval_days FROM concepts "
                "WHERE last_reviewed_at IS NOT NULL"
            ).fetchall()
            for row_id, last_rev, interval in rows:
                try:
                    last_dt = datetime.strptime(last_rev, '%Y-%m-%d %H:%M:%S')
                    new_next = (last_dt + timedelta(days=interval)).strftime('%Y-%m-%d %H:%M:%S')
                    conn.execute(
                        "UPDATE concepts SET next_review_at = ? WHERE id = ?",
                        (new_next, row_id)
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
        for table in ('topics', 'concepts', 'review_log', 'concept_remarks'):
            if not _has_column(table, 'user_id'):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT DEFAULT 'default'")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)")
        conn.commit()
        conn.close()

        # chat_history.db tables
        chat_conn = sqlite3.connect(CHAT_DB)
        if not _has_column('conversations', 'user_id', db_path=CHAT_DB):
            chat_conn.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT DEFAULT 'default'")
            chat_conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)")
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

    _set_schema_version(SCHEMA_VERSION)
    print(f"[LEARN DB] Migrated schema to version {SCHEMA_VERSION}")


# ============================================================================
# Helpers
# ============================================================================

# Regex to strip timezone offset like +08:00 / -05:30 / Z from ISO strings
_TZ_RE = re.compile(r'([+-]\d{2}:\d{2}|Z)$')


def _parse_datetime(dt) -> Optional[datetime]:
    """Parse datetime from string or return as-is if already datetime.
    Handles timezone-aware ISO strings by converting to naive local time."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(tz=None).replace(tzinfo=None)
        return dt
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(tz=None).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
        for fmt in (
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
        ):
            try:
                return datetime.strptime(dt, fmt)
            except ValueError:
                continue
    return None


def _normalize_dt_str(dt_str: Optional[str]) -> Optional[str]:
    """Normalize any datetime string to canonical 'YYYY-MM-DD HH:MM:SS' format."""
    if not dt_str or not isinstance(dt_str, str):
        return dt_str
    parsed = _parse_datetime(dt_str)
    if parsed:
        return parsed.strftime('%Y-%m-%d %H:%M:%S')
    return dt_str


def _now_iso() -> str:
    """Return current time as ISO string."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _conn(db_path=None):
    """Get a connection with row_factory, foreign keys, WAL mode, and busy timeout."""
    c = sqlite3.connect(db_path or KNOWLEDGE_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA busy_timeout = 5000")
    return c


@contextmanager
def _connection(db_path=None):
    """Context manager for database connections. Auto-commits on success, rolls back on error."""
    conn = _conn(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
