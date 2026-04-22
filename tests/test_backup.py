"""Tests for services/backup.py — backup mechanism for SQLite DBs and vector store."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sqlite_db(path: Path) -> None:
    """Create a minimal valid SQLite file at path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS _dummy (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


def _make_vectors_dir(path: Path) -> None:
    """Create a minimal vector store directory skeleton."""
    (path / "collection" / "concepts").mkdir(parents=True, exist_ok=True)
    (path / "collection" / "topics").mkdir(parents=True, exist_ok=True)
    (path / "meta.json").write_text('{"version": 1}')


def _timestamp_dir(base: Path, dt: datetime) -> Path:
    """Return a backup dir path for the given datetime."""
    return base / dt.strftime("%Y-%m-%d_%H-%M-%S")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def env(tmp_path):
    """Set up isolated backup environment in tmp_path and patch all path config."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    knowledge_db = tmp_path / "knowledge.db"
    chat_db = tmp_path / "chat_history.db"
    vectors_dir = tmp_path / "vectors"

    _make_sqlite_db(knowledge_db)
    _make_sqlite_db(chat_db)
    _make_vectors_dir(vectors_dir)

    sqlite_targets = [(knowledge_db, "knowledge.db"), (chat_db, "chat_history.db")]

    with (
        patch("services.backup.config.BACKUP_DIR", backup_dir),
        patch("services.backup.config.BACKUP_RETENTION_DAYS", 7),
        patch("services.backup.config.VECTOR_STORE_PATH", vectors_dir),
        patch("services.backup.SQLITE_TARGETS", sqlite_targets),
        patch("services.backup.db.vectors.close_client", MagicMock()),
    ):
        yield {
            "backup_dir": backup_dir,
            "knowledge_db": knowledge_db,
            "chat_db": chat_db,
            "vectors_dir": vectors_dir,
        }


# ---------------------------------------------------------------------------
# test_perform_backup_creates_structure
# ---------------------------------------------------------------------------


def test_perform_backup_creates_structure(env):
    """perform_backup() creates a timestamped dir with all three targets."""
    from services.backup import perform_backup

    result_path = perform_backup()
    dest = Path(result_path)

    assert dest.exists(), "Backup directory was not created"
    assert (dest / "knowledge.db").exists(), "knowledge.db missing"
    assert (dest / "chat_history.db").exists(), "chat_history.db missing"
    assert (dest / "vectors").is_dir(), "vectors/ directory missing"
    assert (dest / "vectors" / "meta.json").exists(), "vectors/meta.json missing"

    # No temp dir should remain
    tmp_dirs = list(env["backup_dir"].glob(".tmp_*"))
    assert tmp_dirs == [], f"Temp dir not cleaned up: {tmp_dirs}"


def test_perform_backup_dir_name_format(env):
    """Backup dir name matches YYYY-MM-DD_HH-MM-SS_ffffff format."""
    from services.backup import perform_backup

    result_path = perform_backup()
    name = Path(result_path).name
    # Should parse without error
    datetime.strptime(name, "%Y-%m-%d_%H-%M-%S_%f")


def test_backup_sqlite_produces_valid_db(env):
    """The backed-up SQLite file is a valid, queryable database."""
    from services.backup import perform_backup

    result_path = perform_backup()
    dest_db = Path(result_path) / "knowledge.db"

    conn = sqlite3.connect(dest_db)
    conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()


# ---------------------------------------------------------------------------
# test_perform_backup_atomic_on_failure
# ---------------------------------------------------------------------------


def test_perform_backup_atomic_on_failure(env):
    """On failure, no final backup dir is left and the temp dir is cleaned up."""
    from services import backup as backup_module

    with patch.object(backup_module, "_backup_sqlite", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            backup_module.perform_backup()

    final_dirs = [
        d for d in env["backup_dir"].iterdir() if d.is_dir() and not d.name.startswith(".tmp_")
    ]
    tmp_dirs = list(env["backup_dir"].glob(".tmp_*"))

    assert final_dirs == [], f"Partial backup dir left behind: {final_dirs}"
    assert tmp_dirs == [], f"Temp dir not cleaned up after failure: {tmp_dirs}"


def test_perform_backup_retries_temp_dir_rename(env):
    """perform_backup() retries temp-dir promotion on transient PermissionError."""
    from services import backup as backup_module

    original_replace = backup_module.os.replace
    calls = {"count": 0}

    def flaky_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("locked by sync client")
        return original_replace(src, dst)

    with (
        patch.object(backup_module.os, "replace", side_effect=flaky_replace),
        patch.object(backup_module.time, "sleep", return_value=None),
    ):
        result_path = backup_module.perform_backup()

    assert calls["count"] == 2
    assert Path(result_path).exists(), "Backup directory should exist after retry succeeds"


# ---------------------------------------------------------------------------
# test_prune_removes_old_keeps_new
# ---------------------------------------------------------------------------


def test_prune_removes_old_keeps_new(env):
    """prune_old_backups() removes dirs older than retention, keeps recent ones."""
    from services.backup import prune_old_backups

    now = datetime.now()
    backup_dir = env["backup_dir"]

    # Create two old dirs (should be pruned)
    old1 = _timestamp_dir(backup_dir, now - timedelta(days=8))
    old2 = _timestamp_dir(backup_dir, now - timedelta(days=10))
    old1.mkdir()
    old2.mkdir()

    # Create two recent dirs (must be kept)
    recent1 = _timestamp_dir(backup_dir, now - timedelta(days=3))
    recent2 = _timestamp_dir(backup_dir, now - timedelta(days=1))
    recent1.mkdir()
    recent2.mkdir()

    pruned = prune_old_backups()

    assert pruned == 2, f"Expected 2 pruned, got {pruned}"
    assert not old1.exists(), "old1 should have been deleted"
    assert not old2.exists(), "old2 should have been deleted"
    assert recent1.exists(), "recent1 should NOT have been deleted"
    assert recent2.exists(), "recent2 should NOT have been deleted"


def test_prune_respects_fourteen_day_window(env):
    """A 14-day retention window keeps 13-day backups and prunes 15-day ones."""
    from services.backup import prune_old_backups

    now = datetime.now()
    backup_dir = env["backup_dir"]

    old_dir = _timestamp_dir(backup_dir, now - timedelta(days=15))
    kept_dir = _timestamp_dir(backup_dir, now - timedelta(days=13))
    old_dir.mkdir()
    kept_dir.mkdir()

    with patch("services.backup.config.BACKUP_RETENTION_DAYS", 14):
        pruned = prune_old_backups()

    assert pruned == 1
    assert not old_dir.exists()
    assert kept_dir.exists()


def test_get_latest_backup_datetime_returns_newest_valid_snapshot(env):
    """Newest valid timestamped backup dir should drive scheduler timing."""
    from services.backup import get_latest_backup_datetime

    now = datetime.now()
    backup_dir = env["backup_dir"]

    older = _timestamp_dir(backup_dir, now - timedelta(days=2))
    newer = backup_dir / (now - timedelta(hours=6)).strftime("%Y-%m-%d_%H-%M-%S_%f")
    older.mkdir()
    newer.mkdir()
    (backup_dir / ".tmp_2026-04-22_10-00-00_000000").mkdir()
    (backup_dir / "manual_backup").mkdir()

    latest = get_latest_backup_datetime()

    assert latest == datetime.strptime(newer.name, "%Y-%m-%d_%H-%M-%S_%f")


# ---------------------------------------------------------------------------
# test_prune_ignores_non_timestamp_dirs
# ---------------------------------------------------------------------------


def test_prune_ignores_non_timestamp_dirs(env):
    """prune_old_backups() skips non-timestamp entries without crashing."""
    from services.backup import prune_old_backups

    backup_dir = env["backup_dir"]

    # Non-conforming entries
    (backup_dir / "README.txt").write_text("do not delete")
    (backup_dir / "manual_backup").mkdir()
    (backup_dir / "2026-04-99_99-99-99").mkdir()  # invalid date values

    # Should not raise
    pruned = prune_old_backups()

    assert pruned == 0
    assert (backup_dir / "README.txt").exists()
    assert (backup_dir / "manual_backup").exists()


# ---------------------------------------------------------------------------
# test_run_backup_cycle_returns_string_on_error
# ---------------------------------------------------------------------------


def test_run_backup_cycle_returns_string_on_error(env):
    """run_backup_cycle() returns an error string rather than raising."""
    from services import backup as backup_module

    with patch.object(
        backup_module, "perform_backup", side_effect=RuntimeError("simulated failure")
    ):
        result = backup_module.run_backup_cycle()

    assert isinstance(result, str), "run_backup_cycle() must always return a string"
    assert "error" in result.lower() or "fail" in result.lower() or "simulated failure" in result


def test_run_backup_cycle_success_string(env):
    """run_backup_cycle() returns a human-readable success summary."""
    from services.backup import run_backup_cycle

    result = run_backup_cycle()

    assert isinstance(result, str)
    assert result.startswith("Backup saved: `")
    assert "Pruning failed" not in result


def test_backup_sqlite_missing_source_raises(env):
    """_backup_sqlite raises when the source database does not exist.

    sqlite3.connect() silently creates an empty file when given a missing
    path, so without an explicit check a 'successful' backup of a phantom
    empty DB would be written. Verify the production code surfaces this.
    """
    from services import backup as backup_module

    missing_db = env["knowledge_db"].parent / "ghost.db"
    assert not missing_db.exists()

    # Patch SQLITE_TARGETS to point at the non-existent file
    targets = [(missing_db, "ghost.db"), (env["chat_db"], "chat_history.db")]
    with patch("services.backup.SQLITE_TARGETS", targets):
        with pytest.raises(FileNotFoundError):
            backup_module.perform_backup()
