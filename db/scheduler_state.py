"""Persisted scheduler state and process-ownership lock helpers."""

from datetime import datetime, timedelta

from db.core import _conn, _connection, _now_iso, _parse_datetime


def get_scheduler_states() -> dict[str, dict]:
    """Return scheduler job state keyed by job name."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT job_name, last_run_at, last_success_at, last_error, updated_at "
            "FROM scheduler_state"
        ).fetchall()
        return {
            row["job_name"]: {
                "job_name": row["job_name"],
                "last_run_at": row["last_run_at"],
                "last_success_at": row["last_success_at"],
                "last_error": row["last_error"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }
    finally:
        conn.close()


def get_scheduler_state(job_name: str) -> dict | None:
    """Return persisted state for one scheduler job, if present."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT job_name, last_run_at, last_success_at, last_error, updated_at "
            "FROM scheduler_state WHERE job_name = ?",
            (job_name,),
        ).fetchone()
        if not row:
            return None
        return {
            "job_name": row["job_name"],
            "last_run_at": row["last_run_at"],
            "last_success_at": row["last_success_at"],
            "last_error": row["last_error"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def upsert_scheduler_state(
    job_name: str,
    *,
    last_run_at: str | None = None,
    last_success_at: str | None = None,
    last_error: str | None = None,
) -> None:
    """Insert or update scheduler state for a job."""
    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduler_state (
                job_name,
                last_run_at,
                last_success_at,
                last_error,
                updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_name) DO UPDATE SET
                last_run_at = excluded.last_run_at,
                last_success_at = excluded.last_success_at,
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (job_name, last_run_at, last_success_at, last_error, _now_iso()),
        )


def get_scheduler_owner() -> dict | None:
    """Return the current scheduler owner row, if any."""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT singleton, owner_pid, owner_label, heartbeat_at, updated_at "
            "FROM scheduler_owner WHERE singleton = 1"
        ).fetchone()
        if not row:
            return None
        return {
            "singleton": row["singleton"],
            "owner_pid": row["owner_pid"],
            "owner_label": row["owner_label"],
            "heartbeat_at": row["heartbeat_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def acquire_scheduler_owner(
    owner_pid: int,
    owner_label: str,
    stale_seconds: int,
    *,
    now: str | None = None,
) -> bool:
    """Acquire or steal the singleton scheduler owner row if stale."""
    now_value = now or _now_iso()
    now_dt = _parse_datetime(now_value) or datetime.now()

    with _connection() as conn:
        row = conn.execute(
            "SELECT owner_pid, owner_label, heartbeat_at FROM scheduler_owner WHERE singleton = 1"
        ).fetchone()
        if row:
            heartbeat_dt = _parse_datetime(row["heartbeat_at"])
            is_stale = True
            if heartbeat_dt is not None:
                is_stale = heartbeat_dt <= now_dt - timedelta(seconds=stale_seconds)

            same_owner = row["owner_pid"] == owner_pid and row["owner_label"] == owner_label
            if not same_owner and not is_stale:
                return False

        conn.execute(
            """
            INSERT INTO scheduler_owner (
                singleton,
                owner_pid,
                owner_label,
                heartbeat_at,
                updated_at
            ) VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                owner_pid = excluded.owner_pid,
                owner_label = excluded.owner_label,
                heartbeat_at = excluded.heartbeat_at,
                updated_at = excluded.updated_at
            """,
            (owner_pid, owner_label, now_value, now_value),
        )
        return True


def heartbeat_scheduler_owner(owner_pid: int, *, now: str | None = None) -> bool:
    """Refresh the heartbeat if this process still owns the scheduler."""
    now_value = now or _now_iso()
    with _connection() as conn:
        cursor = conn.execute(
            "UPDATE scheduler_owner SET heartbeat_at = ?, updated_at = ? "
            "WHERE singleton = 1 AND owner_pid = ?",
            (now_value, now_value, owner_pid),
        )
        return cursor.rowcount > 0


def release_scheduler_owner(owner_pid: int) -> bool:
    """Release ownership if held by the given process id."""
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM scheduler_owner WHERE singleton = 1 AND owner_pid = ?",
            (owner_pid,),
        )
        return cursor.rowcount > 0
