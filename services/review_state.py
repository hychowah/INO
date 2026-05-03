"""Shared active-review and scheduled-reminder state helpers."""

import logging
import re
from datetime import datetime, timedelta

import config
import db

logger = logging.getLogger("review_state")


def get_pending_review() -> dict | None:
    """Return the active single-concept review using the typed reminder as authority."""
    return get_active_scheduled_review_reminder()


def restore_pending_review_context() -> dict | None:
    """Restore quiz anchor state from an unresolved typed reminder when possible."""
    pending = get_pending_review()
    if not pending:
        return None

    concept_id = pending.get("concept_id")
    if concept_id is None:
        return None

    concept = db.get_concept(int(concept_id))
    if not concept:
        resolve_scheduler_reminder("cancelled")
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


def get_active_scheduled_review_reminder() -> dict | None:
    """Return the active scheduler reminder."""
    reminder = db.get_scheduled_review_reminder()
    if reminder:
        concept = db.get_concept(int(reminder["concept_id"]))
        if not concept:
            logger.warning(
                "Resolving scheduled review reminder for missing concept: concept_id=%s",
                reminder["concept_id"],
            )
            resolve_scheduler_reminder("cancelled")
            return None
        reminder = dict(reminder)
        reminder["concept_title"] = concept["title"]
        reminder["question"] = reminder.get("question_text", "")
        reminder["sent_at"] = reminder.get("last_sent_at") or reminder.get("first_sent_at")
        return reminder
    return None


def set_scheduler_reminder(concept_id: int, question: str) -> None:
    sent_at = db._now_iso()
    db.upsert_scheduled_review_reminder(
        concept_id,
        question,
        first_sent_at=sent_at,
        last_sent_at=sent_at,
        reminder_count=0,
    )


def register_interactive_review_delivery(concept_id: int, question: str) -> None:
    """Register a successfully delivered interactive review question."""
    bind_single_quiz_context(concept_id, question=question)
    sent_at = db._now_iso()
    db.upsert_scheduled_review_reminder(
        concept_id,
        question[:500],
        first_sent_at=sent_at,
        last_sent_at=sent_at,
        reminder_count=0,
    )


def register_scheduler_review_delivery(
    concept_id: int, question: str, *, concept_title: str | None = None
) -> None:
    """Register a successfully delivered scheduler review question."""
    bind_single_quiz_context(concept_id, question=question)
    del concept_title
    set_scheduler_reminder(concept_id, question[:500])


def update_pending_review_delivery(pending: dict) -> dict:
    pending = dict(pending)
    pending["reminder_count"] = int(pending.get("reminder_count", 0)) + 1
    pending["sent_at"] = datetime.now().isoformat()
    db.update_scheduled_review_reminder_delivery(
        pending["reminder_count"],
        last_sent_at=db._parse_datetime(pending["sent_at"]).strftime("%Y-%m-%d %H:%M:%S"),
    )
    return pending


def note_scheduler_reminder_delivery(pending: dict) -> dict:
    """Record a delivered reminder and refresh active quiz context."""
    bind_single_quiz_context(int(pending["concept_id"]), question=pending.get("question", ""))
    return update_pending_review_delivery(pending)


def decide_scheduler_review_action(*, now: datetime | None = None) -> tuple[str, dict | None]:
    """Return the next scheduler review action after reminder-state evaluation.

    Actions:
    - ``wait``: keep the current pending reminder and do nothing yet.
    - ``remind``: send another reminder for the returned pending reminder.
    - ``send_new``: no blocking pending reminder remains; scheduler may fetch a new due review.
    """
    pending = get_active_scheduled_review_reminder()
    if not pending:
        return "send_new", None

    sent_at_str = pending.get("last_sent_at") or pending.get("first_sent_at") or ""
    sent_at = db._parse_datetime(sent_at_str) or now or datetime.now()
    current_time = now or datetime.now()
    cooldown = timedelta(hours=config.REVIEW_NAG_COOLDOWN_HOURS)
    elapsed = current_time - sent_at

    if elapsed < cooldown:
        logger.debug(
            "Pending review #%s — %.1fh < %sh cooldown, waiting",
            pending.get("concept_id"),
            elapsed.total_seconds() / 3600,
            config.REVIEW_NAG_COOLDOWN_HOURS,
        )
        return "wait", pending

    reminder_count = int(pending.get("reminder_count", 0))
    max_reminders = getattr(config, "REVIEW_REMINDER_MAX", 3)
    if reminder_count >= max_reminders:
        logger.info(
            "Pending review #%s — %s reminders sent, expiring and moving on",
            pending.get("concept_id"),
            reminder_count,
        )
        resolve_scheduler_reminder("expired")
        return "send_new", None

    return "remind", pending


def resolve_scheduler_reminder(status: str) -> None:
    db.resolve_scheduled_review_reminder(status)
