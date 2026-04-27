"""Persistence helpers for scheduled review reminders."""

from db.core import _conn, _connection, _now_iso, _uid

_VALID_STATUSES = frozenset({"pending", "answered", "skipped", "expired", "cancelled"})


def _row_to_dict(row) -> dict | None:
    if not row:
        return None
    return {
        "user_id": row["user_id"],
        "concept_id": row["concept_id"],
        "question_text": row["question_text"],
        "first_sent_at": row["first_sent_at"],
        "last_sent_at": row["last_sent_at"],
        "reminder_count": row["reminder_count"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_scheduled_review_reminder(
    *, user_id: str | None = None, include_resolved: bool = False
) -> dict | None:
    uid = user_id or _uid()
    conn = _conn()
    try:
        query = (
            "SELECT user_id, concept_id, question_text, first_sent_at, last_sent_at, "
            "reminder_count, status, created_at, updated_at "
            "FROM scheduled_review_reminders WHERE user_id = ?"
        )
        params: tuple[str, ...] = (uid,)
        if not include_resolved:
            query += " AND status = 'pending'"
        row = conn.execute(query, params).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def upsert_scheduled_review_reminder(
    concept_id: int,
    question_text: str,
    *,
    first_sent_at: str | None = None,
    last_sent_at: str | None = None,
    reminder_count: int = 0,
    status: str = "pending",
    user_id: str | None = None,
) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"Invalid reminder status: {status}")

    uid = user_id or _uid()
    first_sent = first_sent_at or _now_iso()
    last_sent = last_sent_at or first_sent
    now = _now_iso()

    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO scheduled_review_reminders (
                user_id,
                concept_id,
                question_text,
                first_sent_at,
                last_sent_at,
                reminder_count,
                status,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                concept_id = excluded.concept_id,
                question_text = excluded.question_text,
                first_sent_at = excluded.first_sent_at,
                last_sent_at = excluded.last_sent_at,
                reminder_count = excluded.reminder_count,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                uid,
                int(concept_id),
                question_text,
                first_sent,
                last_sent,
                int(reminder_count),
                status,
                now,
                now,
            ),
        )


def update_scheduled_review_reminder_delivery(
    reminder_count: int, *, last_sent_at: str | None = None, user_id: str | None = None
) -> None:
    uid = user_id or _uid()
    with _connection() as conn:
        conn.execute(
            "UPDATE scheduled_review_reminders SET reminder_count = ?, last_sent_at = ?, "
            "updated_at = ? WHERE user_id = ? AND status = 'pending'",
            (int(reminder_count), last_sent_at or _now_iso(), _now_iso(), uid),
        )


def resolve_scheduled_review_reminder(status: str, *, user_id: str | None = None) -> None:
    if status not in _VALID_STATUSES or status == "pending":
        raise ValueError(f"Invalid resolved reminder status: {status}")

    uid = user_id or _uid()
    with _connection() as conn:
        conn.execute(
            "UPDATE scheduled_review_reminders SET status = ?, updated_at = ? "
            "WHERE user_id = ? AND status = 'pending'",
            (status, _now_iso(), uid),
        )


def clear_scheduled_review_reminder(*, user_id: str | None = None) -> None:
    uid = user_id or _uid()
    with _connection() as conn:
        conn.execute("DELETE FROM scheduled_review_reminders WHERE user_id = ?", (uid,))