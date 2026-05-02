"""Shared pending-review and scheduled-reminder state helpers."""

import json
import logging
import re
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

    bind_single_quiz_context(int(concept_id), question=(pending.get("question") or "").strip())

    return pending


def bind_single_quiz_context(concept_id: int, *, question: str | None = None) -> None:
    """Bind the active single-concept quiz context for delivery, recovery, or reminders."""
    db.set_session("active_concept_id", str(concept_id))
    db.set_session("quiz_anchor_concept_id", str(concept_id))
    if question:
        db.set_session("last_quiz_question", question.strip())


def resolve_assess_concept(requested_concept_id: int | None) -> tuple[int | None, dict | None]:
    """Resolve the concept targeted by assess using the established fallback chain."""
    concept = None
    concept_id = requested_concept_id

    if concept_id is not None:
        concept = db.get_concept(int(concept_id))
        if concept:
            return int(concept_id), concept

    anchor_cid = db.get_session("quiz_anchor_concept_id")
    if anchor_cid:
        concept = db.get_concept(int(anchor_cid))
        if concept:
            return int(anchor_cid), concept

    active_cid = db.get_session("active_concept_id")
    if active_cid:
        concept = db.get_concept(int(active_cid))
        if concept:
            return int(active_cid), concept

    history = db.get_chat_history(limit=6)
    for msg in reversed(history):
        match = re.search(r"quiz on concept #(\d+)", msg.get("content", ""))
        if not match:
            continue
        fallback_cid = int(match.group(1))
        concept = db.get_concept(fallback_cid)
        if concept:
            return fallback_cid, concept

    return None, None


def normalize_reminder_timestamp(raw_value: str | None) -> str:
    parsed = db._parse_datetime(raw_value)
    if not parsed:
        if raw_value:
            logger.warning("Invalid pending_review timestamp %r; resetting to now", raw_value)
        return db._now_iso()
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _clear_invalid_pending_review(reason: str, pending: dict | None = None) -> None:
    concept_id = None
    if isinstance(pending, dict):
        concept_id = pending.get("concept_id")
    logger.warning(
        "Clearing invalid pending_review state: reason=%s concept_id=%s",
        reason,
        concept_id,
    )
    clear_pending_review()


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
        _clear_invalid_pending_review("missing_concept_id", pending)
        return None

    try:
        concept_id = int(concept_id)
    except (TypeError, ValueError):
        _clear_invalid_pending_review("non_integer_concept_id", pending)
        return None

    concept = db.get_concept(concept_id)
    if not concept:
        _clear_invalid_pending_review("missing_concept", pending)
        return None

    normalized_sent_at = normalize_reminder_timestamp(pending.get("sent_at"))
    logger.info(
        "Importing legacy pending_review into scheduled_review_reminders: concept_id=%s",
        concept_id,
    )
    db.upsert_scheduled_review_reminder(
        concept_id,
        pending.get("question", ""),
        first_sent_at=normalized_sent_at,
        last_sent_at=normalized_sent_at,
        reminder_count=int(pending.get("reminder_count", 0)),
    )
    reminder = db.get_scheduled_review_reminder()
    if not reminder:
        return None

    reminder = dict(reminder)
    reminder["concept_title"] = pending.get("concept_title") or concept["title"]
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


def register_interactive_review_delivery(concept_id: int, question: str) -> None:
    """Register a successfully delivered interactive review question."""
    bind_single_quiz_context(concept_id, question=question)
    set_pending_review(concept_id, question)


def register_scheduler_review_delivery(
    concept_id: int, question: str, *, concept_title: str | None = None
) -> None:
    """Register a successfully delivered scheduler review question."""
    bind_single_quiz_context(concept_id, question=question)
    title = concept_title
    if title is None:
        concept = db.get_concept(concept_id)
        title = concept["title"] if concept else "Unknown"
    set_scheduler_reminder(concept_id, title, question[:500])


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


def note_scheduler_reminder_delivery(pending: dict) -> dict:
    """Record a delivered reminder and refresh active quiz context."""
    bind_single_quiz_context(int(pending["concept_id"]), question=pending.get("question", ""))
    return update_pending_review_delivery(pending)


def resolve_scheduler_reminder(status: str) -> None:
    db.resolve_scheduled_review_reminder(status)
    clear_pending_review()