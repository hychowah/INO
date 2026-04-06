"""
Backup service — periodic snapshots of all persistent data stores.

Creates timestamped backup directories under config.BACKUP_DIR containing:
  - knowledge.db    (SQLite knowledge base)
  - chat_history.db (SQLite chat history)
  - vectors/        (Qdrant embedded vector store)

Retention: keeps the last BACKUP_RETENTION_DAYS days of backups; older
directories are pruned after each run.
"""

import logging
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import config
import db.vectors
from db import core as db_core

logger = logging.getLogger("learn.backup")

# Ordered list of (source_path, filename_in_backup) for all SQLite databases.
# To add a new database: append one entry here — no other changes needed.
SQLITE_TARGETS: list[tuple[Path, str]] = [
    (db_core.KNOWLEDGE_DB, "knowledge.db"),
    (db_core.CHAT_DB, "chat_history.db"),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _backup_sqlite(src_path: Path, dest_path: Path) -> None:
    """Copy a SQLite database using the safe online-backup API.

    sqlite3.Connection.backup() coordinates with any open write transactions
    so the copy is always consistent, even if the DB is in active use.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if not src_path.exists():
        raise FileNotFoundError(f"[BACKUP] Source database not found: {src_path}")
    src_conn = sqlite3.connect(src_path)
    try:
        dst_conn = sqlite3.connect(dest_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _backup_vectors(src_dir: Path, dest_dir: Path) -> None:
    """Copy the Qdrant embedded vector store directory.

    The Qdrant client singleton is closed before copying to release any
    platform file locks (required on Windows, harmless on Linux/macOS).
    The next call to db.vectors will re-initialize the client lazily.
    """
    if not src_dir.exists():
        logger.warning(f"[BACKUP] Vector store directory not found, skipping: {src_dir}")
        return

    db.vectors.close_client()
    shutil.copytree(src_dir, dest_dir)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def perform_backup() -> str:
    """Create a full backup snapshot and return the backup directory path.

    Uses an atomic write pattern:
      1. Write everything to a hidden `.tmp_TIMESTAMP/` directory.
      2. On success, rename to the final `TIMESTAMP/` directory.
      3. On any failure, delete the temp directory and re-raise.

    Returns:
        Absolute path string of the newly created backup directory.

    Raises:
        Any exception from the underlying copy operations (caller decides
        how to handle; run_backup_cycle catches and converts to a string).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    tmp_dir = config.BACKUP_DIR / f".tmp_{timestamp}"
    final_dir = config.BACKUP_DIR / timestamp

    try:
        tmp_dir.mkdir(parents=True, exist_ok=False)

        # Back up each SQLite database
        for src_path, filename in SQLITE_TARGETS:
            _backup_sqlite(src_path, tmp_dir / filename)

        # Back up the vector store
        _backup_vectors(config.VECTOR_STORE_PATH, tmp_dir / "vectors")

        # Atomic commit: rename temp dir to final name
        tmp_dir.rename(final_dir)
        logger.info(f"[BACKUP] Snapshot complete: {final_dir}")
        return str(final_dir)

    except Exception:
        # Best-effort cleanup of the partial temp directory
        if tmp_dir.exists():
            try:
                shutil.rmtree(tmp_dir)
            except Exception as cleanup_err:
                logger.warning(f"[BACKUP] Failed to clean up temp dir {tmp_dir}: {cleanup_err}")
        raise


def prune_old_backups() -> int:
    """Delete backup directories older than config.BACKUP_RETENTION_DAYS.

    Only directories whose names match the `YYYY-MM-DD_HH-MM-SS` format are
    considered. Non-conforming entries (README files, manually placed dirs,
    etc.) are silently skipped with a warning log so pruning continues.

    Returns:
        Number of directories deleted.
    """
    if not config.BACKUP_DIR.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=config.BACKUP_RETENTION_DAYS)
    pruned = 0

    for entry in config.BACKUP_DIR.iterdir():
        if not entry.is_dir():
            continue
        try:
            # Support both YYYY-MM-DD_HH-MM-SS (old) and YYYY-MM-DD_HH-MM-SS_ffffff (new)
            name = entry.name.rsplit("_", 1)[0] if entry.name.count("_") == 2 else entry.name
            entry_dt = datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
        except ValueError:
            logger.warning(f"[BACKUP] Skipping non-timestamp entry during prune: {entry.name}")
            continue

        if entry_dt < cutoff:
            try:
                shutil.rmtree(entry)
                logger.info(f"[BACKUP] Pruned old backup: {entry.name}")
                pruned += 1
            except Exception as e:
                logger.error(f"[BACKUP] Failed to delete {entry}: {e}")

    return pruned


def run_backup_cycle() -> str:
    """Run a full backup and prune cycle.

    This is the single entry point used by both the scheduler and the
    Discord `/backup` command.

    Returns:
        A human-readable summary string. Never raises — errors are caught
        and included in the return value so callers always get a message.
    """
    try:
        backup_path = perform_backup()
    except Exception as e:
        logger.error(f"[BACKUP] Backup cycle failed: {e}", exc_info=True)
        return f"Backup failed: {e}"

    backup_name = Path(backup_path).name
    try:
        pruned = prune_old_backups()
        prune_msg = f" | Pruned {pruned} old backup(s)" if pruned else ""
    except Exception as e:
        logger.warning(f"[BACKUP] Pruning failed: {e}", exc_info=True)
        prune_msg = " | Pruning failed (see logs)"

    return f"Backup saved: `{backup_name}`{prune_msg}"
