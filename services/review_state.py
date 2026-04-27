"""Shared pending-review and scheduled-reminder state helpers."""

import json
import logging
from datetime import datetime

import db

logger = logging.getLogger("review_state")


def get_pending_review() -> dict | None:
    """Read pending review state from the session store."""
    raw = db.get_session("pending_review")
    if not raw:
        return None
    try:
        pending = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt pending_review in session state — clearing")
        db.set_session("pending_review", None)
        return None

    if not isinstance(pending, dict):
        db.set_session("pending_review", None)
        return None
    return pending


def set_pending_review(
    concept_id: int,
    question: str,
    *,
    concept_title: str | None = None,
    sent_at: str | None = None,
    reminder_count: int = 0,
) -> None:
    """Persist a single outstanding review question for late-answer recovery."""
    title = concept_title
    if title is None:
        concept = db.get_concept(concept_id)
        title = concept["title"] if concept else "Unknown"

    blob = {
        "concept_id": int(concept_id),
        "concept_title": title,
        "question": (question or "")[:500],
        "sent_at": sent_at or datetime.now().isoformat(),
        "reminder_count": int(reminder_count),
    }
    db.set_session("pending_review", json.dumps(blob))


def clear_pending_review() -> None:
    db.set_session("pending_review", None)


def restore_pending_review_context() -> dict | None:
    """Restore quiz anchor state from an unresolved pending review when possible."""
    pending = get_pending_review()
    if not pending:
        return None

    concept_id = pending.get("concept_id")
    if concept_id is None:
        clear_pending_review()
        return None

    concept = db.get_concept(int(concept_id))
    if not concept:
        clear_pending_review()
        return None

    db.set_session("active_concept_id", str(concept_id))
    db.set_session("quiz_anchor_concept_id", str(concept_id))

    question = (pending.get("question") or "").strip()
    if question:
        db.set_session("last_quiz_question", question)

    return pending


def normalize_reminder_timestamp(raw_value: str | None) -> str:
    parsed = db._parse_datetime(raw_value)
    if not parsed:
        return db._now_iso()
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def get_active_scheduled_review_reminder() -> dict | None:
    """Return the active scheduler reminder, importing legacy pending state if needed."""
    reminder = db.get_scheduled_review_reminder()
    if reminder:
        concept = db.get_concept(int(reminder["concept_id"]))
        reminder = dict(reminder)
        reminder["concept_title"] = concept["title"] if concept else "Unknown"
        reminder["question"] = reminder.get("question_text", "")
        reminder["sent_at"] = reminder.get("last_sent_at") or reminder.get("first_sent_at")
        return reminder

    pending = get_pending_review()
    if not pending:
        return None

    concept_id = pending.get("concept_id")
    if concept_id is None:
        return None

    normalized_sent_at = normalize_reminder_timestamp(pending.get("sent_at"))
    db.upsert_scheduled_review_reminder(
        int(concept_id),
        pending.get("question", ""),
        first_sent_at=normalized_sent_at,
        last_sent_at=normalized_sent_at,
        reminder_count=int(pending.get("reminder_count", 0)),
    )
    reminder = db.get_scheduled_review_reminder()
    if not reminder:
        return None

    reminder = dict(reminder)
    reminder["concept_title"] = pending.get("concept_title", "Unknown")
    reminder["question"] = pending.get("question", "")
    reminder["sent_at"] = normalized_sent_at
    return reminder


def set_scheduler_reminder(concept_id: int, concept_title: str, question: str) -> None:
    sent_at = db._now_iso()
    db.upsert_scheduled_review_reminder(
        concept_id,
        question,
        first_sent_at=sent_at,
        last_sent_at=sent_at,
        reminder_count=0,
    )
    set_pending_review(concept_id, question, concept_title=concept_title)


def update_pending_review_delivery(pending: dict) -> dict:
    pending = dict(pending)
    pending["reminder_count"] = int(pending.get("reminder_count", 0)) + 1
    pending["sent_at"] = datetime.now().isoformat()
    set_pending_review(
        int(pending["concept_id"]),
        pending.get("question", ""),
        concept_title=pending.get("concept_title"),
        sent_at=pending["sent_at"],
        reminder_count=pending["reminder_count"],
    )
    db.update_scheduled_review_reminder_delivery(
        pending["reminder_count"],
        last_sent_at=normalize_reminder_timestamp(pending["sent_at"]),
    )
    return pending


def resolve_scheduler_reminder(status: str) -> None:
    db.resolve_scheduled_review_reminder(status)
    clear_pending_review()