"""
Database core — connection helpers and initialization.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

# Database paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"


def _uid() -> str:
    """Get the current user_id from the ContextVar (default='default').

    Lazy import to avoid circular dependency between db and services layers.
    Used as the default user_id in db functions that accept *, user_id=None.
    """
    from services.state import get_current_user

    return get_current_user()


def _resolve_repo_path(env_name: str, default_path: Path) -> Path:
    """Resolve an optional repo-relative path override from the environment."""
    raw = os.environ.get(env_name)
    if not raw:
        return default_path

    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


KNOWLEDGE_DB = _resolve_repo_path("LEARN_DB_PATH", DATA_DIR / "knowledge.db")
CHAT_DB = _resolve_repo_path("LEARN_CHAT_DB_PATH", DATA_DIR / "chat_history.db")

# Configuration
MAX_CHAT_HISTORY = 100
CHAT_CLEANUP_DAYS = 7
CLEANUP_THROTTLE_SECONDS = 600  # only run cleanup every 10 minutes

# Schema version — bump this when adding migrations
SCHEMA_VERSION = 14


# ============================================================================
# Initialization & Migrations
# ============================================================================


def init_databases():
    """Initialize all databases with schema, then run migrations."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_DB.parent.mkdir(parents=True, exist_ok=True)
    CHAT_DB.parent.mkdir(parents=True, exist_ok=True)
    _init_knowledge_db()
    _init_chat_db()
    _run_migrations()
    _init_vector_store()


def _init_vector_store():
    """Initialize the Qdrant vector store (best-effort — non-fatal on failure)."""
    try:
        from db.vectors import init_vector_store

        init_vector_store()
    except Exception as e:
        import logging

        logging.getLogger("learn.db").warning(
            f"Vector store init skipped: {e}. Semantic search will fall back to FTS5."
        )


def _init_knowledge_db():
    """Create knowledge database schema."""
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            user_id TEXT NOT NULL DEFAULT 'default',
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
            user_id TEXT NOT NULL DEFAULT 'default',
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
            user_id TEXT NOT NULL DEFAULT 'default',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS review_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
            question_asked TEXT,
            user_response TEXT,
            quality INTEGER,
            llm_assessment TEXT,
            user_id TEXT NOT NULL DEFAULT 'default',
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
        CREATE INDEX IF NOT EXISTS idx_topics_user_id ON topics(user_id);
        CREATE INDEX IF NOT EXISTS idx_concepts_user_id ON concepts(user_id);
        CREATE INDEX IF NOT EXISTS idx_review_log_user_id ON review_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_concept_remarks_user_id ON concept_remarks(user_id);

        CREATE TABLE IF NOT EXISTS pending_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            discord_message_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            discord_id TEXT UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Ensure the default user exists for single-user / backward-compat operation
    conn.execute(
        "INSERT OR IGNORE INTO users (id, display_name) VALUES ('default', 'Default User')"
    )
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
            user_id TEXT NOT NULL DEFAULT 'default',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_conversations_lookup
        ON conversations(session_id, timestamp DESC);

        CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);

        CREATE TABLE IF NOT EXISTS session_state (
            user_id TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            value TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, key)
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


def _has_table(table: str, db_path=None) -> bool:
    """Check if a table exists in a database (safe for migrations).
    Uses KNOWLEDGE_DB by default; pass db_path for other databases."""
    conn = sqlite3.connect(db_path or KNOWLEDGE_DB)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    result = cursor.fetchone() is not None
    conn.close()
    return result


def _run_migrations():
    """Run all pending migrations. Delegated to db.migrations module."""
    from db.migrations import _run_migrations as _do_migrations

    _do_migrations()


# ============================================================================
# Helpers
# ============================================================================

# Regex to strip timezone offset like +08:00 / -05:30 / Z from ISO strings
_TZ_RE = re.compile(r"([+-]\d{2}:\d{2}|Z)$")


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
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
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
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return dt_str


def _now_iso() -> str:
    """Return current time as ISO string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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
