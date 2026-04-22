"""
Learning review scheduler — background task that checks for due reviews
every N minutes and sends Discord DMs with quiz questions.

Pending review tracking (DB-backed, survives restarts):
  session_state key 'pending_review' stores a JSON blob:
  {"concept_id": 12, "concept_title": "...", "question": "...",
   "sent_at": "ISO-datetime", "reminder_count": 0}
  Set AFTER a review DM is confirmed sent; cleared only by _handle_assess
  or when max reminders are exhausted.
"""

import asyncio
import inspect
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import discord

import config
import db
from bot.messages import send_review_question
from services import backup as backup_service
from services import pipeline, state
from services.dedup import format_dedup_suggestions
from services.formatting import truncate_for_discord
from services.views import DedupConfirmView

logger = logging.getLogger("scheduler")

# Module-level state set by start()
_bot = None
_authorized_user_id = None
_review_task: asyncio.Task | None = None
_shared_task: asyncio.Task | None = None
_owner_pid = os.getpid()

_TICK_SECONDS = 60
_REVIEW_STARTUP_DELAY_SECONDS = 30
_OWNER_STALE_SECONDS = _TICK_SECONDS * 3


@dataclass(frozen=True)
class _ScheduledJob:
    name: str
    interval_seconds: Callable[[], int]
    runner: Callable[[], Awaitable[None] | None]


# ============================================================================
# Pending review helpers
# ============================================================================


def _get_pending_review() -> dict | None:
    """Read pending review blob from session state. Returns dict or None."""
    raw = db.get_session("pending_review")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt pending_review in session state — clearing")
        db.set_session("pending_review", None)
        return None


def _set_pending_review(concept_id: int, concept_title: str, question: str) -> None:
    """Write a new pending review blob. Called AFTER DM is confirmed sent."""
    blob = {
        "concept_id": concept_id,
        "concept_title": concept_title,
        "question": question,
        "sent_at": datetime.now().isoformat(),
        "reminder_count": 0,
    }
    db.set_session("pending_review", json.dumps(blob))
    logger.debug(f"Set pending review: concept #{concept_id}")


def _update_pending_reminder(pending: dict) -> None:
    """Increment reminder count + reset sent_at after sending a reminder."""
    pending["reminder_count"] = pending.get("reminder_count", 0) + 1
    pending["sent_at"] = datetime.now().isoformat()
    db.set_session("pending_review", json.dumps(pending))


def _clear_pending_review() -> None:
    """Clear pending review state (max reminders exhausted or concept deleted)."""
    db.set_session("pending_review", None)
    logger.debug("Cleared pending review state")


# ============================================================================
# Review check & send
# ============================================================================


async def _check_reviews():
    """Check for due concepts and send review quizzes via DM.

    Flow:
    1. Suppress if user is in an active session.
    2. If a review is pending (unanswered):
       a. Concept deleted? → clear pending, fall through to normal flow.
       b. < cooldown elapsed? → skip entirely (wait for user).
       c. ≥ cooldown & reminders left? → send static reminder, return.
       d. Max reminders reached? → clear pending, fall through.
    3. No pending review → pick next due concept, send LLM-generated quiz.
    """
    with state.pipeline_serialized_nowait() as acquired:
        if not acquired:
            logger.debug("Skipping review check — pipeline busy")
            return

        if state.last_activity_at:
            cutoff = datetime.now() - timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)
            if state.last_activity_at > cutoff:
                logger.debug("Skipping review check — user active in session")
                return

        logger.debug("Running review-check...")

        # Suppress if /review command is actively generating a quiz
        if db.get_session("review_in_progress"):
            logger.debug("Skipping review check — /review command in progress")
            return

        pending = _get_pending_review()
        if pending:
            cid = pending.get("concept_id")
            if cid and not db.get_concept(cid):
                logger.info(f"Pending concept #{cid} no longer exists — clearing")
                _clear_pending_review()
            else:
                sent_at_str = pending.get("sent_at", "")
                try:
                    sent_at = datetime.fromisoformat(sent_at_str)
                except (ValueError, TypeError):
                    sent_at = datetime.now()

                cooldown = timedelta(hours=config.REVIEW_NAG_COOLDOWN_HOURS)
                elapsed = datetime.now() - sent_at

                if elapsed < cooldown:
                    logger.debug(
                        f"Pending review #{cid} — {elapsed.total_seconds() / 3600:.1f}h "
                        f"< {config.REVIEW_NAG_COOLDOWN_HOURS}h cooldown, skipping"
                    )
                    return

                reminder_count = pending.get("reminder_count", 0)
                max_reminders = getattr(config, "REVIEW_REMINDER_MAX", 3)

                if reminder_count >= max_reminders:
                    logger.info(
                        f"Pending review #{cid} — {reminder_count} reminders sent, "
                        f"giving up and moving to next concept"
                    )
                    _clear_pending_review()
                else:
                    await _send_review_reminder(pending)
                    return

        try:
            review_lines = pipeline.handle_review_check()

            if not review_lines:
                logger.debug("No pending reviews")
                return

            line = review_lines[0]
            logger.info(f"Review due: {line[:80]}")
            await _send_review_quiz(line)

        except Exception as e:
            logger.error(f"Error in review-check: {e}", exc_info=True)


async def _send_review_reminder(pending: dict):
    """Send a static reminder DM for an unanswered review (no LLM call).
    Also re-sets active_concept_id so the assess pipeline works when the
    user eventually replies."""
    if not _bot or not _authorized_user_id:
        return

    cid = pending.get("concept_id")
    title = pending.get("concept_title", "Unknown")
    reminder_count = pending.get("reminder_count", 0) + 1
    max_reminders = getattr(config, "REVIEW_REMINDER_MAX", 3)
    remaining = max_reminders - reminder_count

    try:
        user = await _bot.fetch_user(_authorized_user_id)
        if not user:
            return

        if remaining > 0:
            msg = (
                f"📚 **Reminder** — You have a pending review question on "
                f"**{title}**. Reply when you're ready! "
                f"({remaining} reminder{'s' if remaining != 1 else ''} left before I move on)"
            )
        else:
            msg = (
                f"📚 **Reminder** — Last nudge about **{title}**! "
                f"Reply when you're ready, or I'll move to a new concept next time."
            )

        await user.send(msg)
        logger.info(f"Sent review reminder #{reminder_count} for concept #{cid}")

        # Re-set active_concept_id so the assess pipeline knows which
        # concept the user's eventual reply is about
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", str(cid))

        # Update pending state (increment counter, reset timer)
        _update_pending_reminder(pending)

    except discord.Forbidden:
        logger.error("Cannot send DM (forbidden)")
    except Exception as e:
        logger.error(f"Error sending review reminder: {e}", exc_info=True)


async def _send_review_quiz(payload: str):
    """
    Send a review quiz DM using the structured P1 generation flow.
    payload format: concept_id|context_string

    Prompt 1 (reasoning model): Generates the optimal question from pre-loaded data.
    Delivery stage: Deterministically formats the P1 output for user delivery.
    Falls back to single-prompt review-check flow if Prompt 1 fails.
    """
    if not _bot or not _authorized_user_id:
        logger.error("Bot not initialized, can't send review")
        return

    try:
        user = await _bot.fetch_user(_authorized_user_id)
        if not user:
            logger.error(f"Could not find user {_authorized_user_id}")
            return

        # Extract concept_id from payload for pending state
        try:
            cid = int(payload.split("|", 1)[0])
        except (ValueError, IndexError):
            cid = None

        try:
            # Set action source for audit trail
            from services.tools import set_action_source

            set_action_source("scheduler")

            # Set active concept for subsequent assess action
            if cid:
                db.set_session("active_concept_id", str(cid))
                db.set_session("quiz_anchor_concept_id", str(cid))

            review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"

            # --- Two-prompt pipeline (with fallback) ---
            from services.llm import LLMError

            try:
                if cid:
                    p1_result = await pipeline.generate_quiz_question(cid)
                    llm_response = await pipeline.package_quiz_for_discord(p1_result, cid)
                else:
                    raise LLMError("No concept_id in payload", retryable=True)
            except LLMError as e:
                logger.warning(
                    f"Two-prompt pipeline failed ({e}), falling back to single-prompt flow"
                )
                llm_response = await pipeline.call_with_fetch_loop(
                    mode="review-check",
                    text=review_text,
                    author=str(_authorized_user_id),
                )

            # Parse action JSON and extract human-readable message
            final_result = await pipeline.execute_llm_response(review_text, llm_response, "reply")
            _msg_type, message = pipeline.process_output(final_result)

            if message and message.strip():
                # Store the actual question text for accurate review logging
                db.set_session("last_quiz_question", message.strip())
                from bot.handler import _handle_user_message

                await send_review_question(user.send, message, cid, _handle_user_message)
                logger.info("Sent review DM")

                # Set pending review state AFTER DM is confirmed sent.
                # This avoids the race condition where pending is set
                # during the LLM await but the user answers a previous
                # quiz in the meantime.
                if cid:
                    concept = db.get_concept(cid)
                    concept_title = concept["title"] if concept else "Unknown"
                    _set_pending_review(cid, concept_title, message[:500])
            else:
                logger.debug("Empty result for review quiz")

        except ImportError as ie:
            logger.error(f"Import error: {ie}")
            await user.send(
                truncate_for_discord(f"📚 **Learning Review** — Time to review:\n{payload}")
            )

    except discord.Forbidden:
        logger.error("Cannot send DM (forbidden)")
    except Exception as e:
        logger.error(f"Error sending review: {e}", exc_info=True)


async def _send_mode_report(
    mode_label: str,
    icon: str,
    final_result: str,
    proposed_actions: list,
    proposal_type: str,
    execute_fn,
):
    """DM the user a mode report with optional proposed-action buttons.

    Shared by maintenance and taxonomy — only the label/icon/proposal_type differ.
    """
    from services.views import ProposedActionsView

    if not _bot or not _authorized_user_id:
        logger.error(f"Bot not initialized, can't send {mode_label} report")
        return

    try:
        user = await _bot.fetch_user(_authorized_user_id)
        if not user:
            logger.error(f"Could not find user {_authorized_user_id}")
            return

        if final_result and final_result.strip():
            msg = final_result
            if msg.startswith("REPLY: "):
                msg = msg[7:]
            elif msg.startswith("REPLY:"):
                msg = msg[6:]
            if msg.strip():
                await user.send(f"{icon} **{mode_label}**\n\n{msg[:1900]}")
                logger.info(f"Sent {mode_label} report DM")

        if proposed_actions:
            proposal_id = db.save_proposal(proposal_type, proposed_actions)
            view = ProposedActionsView(proposal_id, proposed_actions, execute_fn)
            action_lines = []
            for i, a in enumerate(proposed_actions, 1):
                name = a.get("action", "unknown")
                desc = a.get("message", "")[:80]
                action_lines.append(f"**{i}.** `{name}` — {desc}")
            proposal_text = (
                "⏳ **Actions needing your approval:**\n\n"
                + "\n".join(action_lines)
                + "\n\nUse the buttons below to approve or reject."
            )
            sent_msg = await user.send(content=proposal_text[:1900], view=view)
            db.update_proposal_message_id(proposal_id, sent_msg.id)
            logger.info(f"Sent {len(proposed_actions)} proposed {mode_label} actions")

    except discord.Forbidden:
        logger.error("Cannot send DM (forbidden)")
    except Exception as e:
        logger.error(f"Error sending {mode_label} report: {e}", exc_info=True)


async def _check_maintenance():
    """Run DB diagnostics and send maintenance report if issues found."""
    logger.debug("Running maintenance check...")
    with state.pipeline_serialized_nowait() as acquired:
        if not acquired:
            logger.debug("Skipping maintenance check — pipeline busy")
            return
        try:
            diagnostic_context = pipeline.handle_maintenance()
            if not diagnostic_context:
                logger.debug("Maintenance: no issues found")
                return
            logger.info("Maintenance issues found, sending to LLM for triage")
            await _send_maintenance_report(diagnostic_context)
        except Exception as e:
            logger.error(f"Error in maintenance check: {e}", exc_info=True)


async def _send_maintenance_report(diagnostic_context: str):
    """Send diagnostic context to the LLM for triage, then DM the report."""
    try:
        final_result, proposed_actions = await pipeline.call_maintenance_loop(diagnostic_context)
        await _send_mode_report(
            mode_label="Knowledge Base Maintenance",
            icon="🔧",
            final_result=final_result,
            proposed_actions=proposed_actions,
            proposal_type="maintenance",
            execute_fn=pipeline.execute_maintenance_actions,
        )
    except Exception as e:
        logger.error(f"Error in maintenance pipeline: {e}", exc_info=True)


async def _check_taxonomy():
    """Run taxonomy reorganization and DM the report if there are topics."""
    logger.debug("Running taxonomy check...")
    with state.pipeline_serialized_nowait() as acquired:
        if not acquired:
            logger.debug("Skipping taxonomy check — pipeline busy")
            return
        try:
            taxonomy_context = pipeline.handle_taxonomy()
            if not taxonomy_context:
                logger.debug("Taxonomy: no topics found")
                return
            logger.info("Running taxonomy reorganization LLM loop")
            final_result, proposed_actions = await pipeline.call_taxonomy_loop(taxonomy_context)
            await _send_mode_report(
                mode_label="Weekly Taxonomy Reorganization",
                icon="🌿",
                final_result=final_result,
                proposed_actions=proposed_actions,
                proposal_type="taxonomy",
                execute_fn=pipeline.execute_maintenance_actions,
            )
        except Exception as e:
            logger.error(f"Error in taxonomy check: {e}", exc_info=True)


async def _check_backup():
    """Run a full backup-and-prune cycle (non-blocking via thread executor)."""
    logger.info("[BACKUP] Running scheduled backup...")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, backup_service.run_backup_cycle)
    logger.info(f"[BACKUP] {result}")


async def _check_dedup():
    """Run the dedup sub-agent to find potential duplicates.
    Now proposal-only: stores suggestions in DB and DMs user with buttons."""
    with state.pipeline_serialized_nowait() as acquired:
        if not acquired:
            logger.debug("[DEDUP] Skipping — pipeline busy")
            return

        existing = db.get_pending_proposal("dedup")
        if existing:
            logger.debug("[DEDUP] Skipping — pending proposal exists")
            return

        logger.info("[DEDUP] Running dedup check...")
        try:
            groups = await pipeline.handle_dedup_check()
            if not groups:
                logger.debug("[DEDUP] No duplicates found")
                return

            proposal_id = db.save_proposal("dedup", groups)

            if _bot and _authorized_user_id:
                await _send_dedup_suggestions(proposal_id, groups)

        except Exception as e:
            logger.error(f"Error in dedup check: {e}", exc_info=True)


async def _send_dedup_suggestions(proposal_id: int, groups: list[dict]):
    """DM the user dedup suggestions with approve/reject buttons."""
    try:
        user = await _bot.fetch_user(_authorized_user_id)
        if not user:
            return

        # Format the suggestion message
        suggestion_text = format_dedup_suggestions(groups)

        # Create button view
        view = DedupConfirmView(proposal_id, groups)

        # Send DM with buttons
        msg = await user.send(
            content=suggestion_text[:1900],
            view=view,
        )

        # Store message ID for reference
        db.update_proposal_message_id(proposal_id, msg.id)
        logger.info(
            f"[DEDUP] Sent dedup suggestions ({len(groups)} groups) as proposal #{proposal_id}"
        )

    except Exception as e:
        logger.error(f"Error sending dedup suggestions: {e}", exc_info=True)


def _review_interval_seconds() -> int:
    return max(60, int(config.REVIEW_CHECK_INTERVAL_MINUTES) * 60)


def _backup_interval_seconds() -> int:
    return max(3600, int(config.BACKUP_INTERVAL_HOURS) * 3600)


def _maintenance_interval_seconds() -> int:
    return max(3600, int(config.MAINTENANCE_INTERVAL_HOURS) * 3600)


def _taxonomy_interval_seconds() -> int:
    return max(3600, int(config.TAXONOMY_INTERVAL_HOURS) * 3600)


def _dedup_interval_seconds() -> int:
    return max(3600, int(config.DEDUP_INTERVAL_HOURS) * 3600)


def _proposal_cleanup_interval_seconds() -> int:
    return max(3600, int(config.PROPOSAL_CLEANUP_INTERVAL_HOURS) * 3600)


async def _check_proposal_cleanup():
    db.cleanup_expired_proposals()


_REVIEW_JOB = _ScheduledJob("review_check", _review_interval_seconds, _check_reviews)
_shared_jobs = []
if config.MAINTENANCE_MODE_ENABLED:
    _shared_jobs.append(
        _ScheduledJob("maintenance", _maintenance_interval_seconds, _check_maintenance)
    )
_shared_jobs.append(_ScheduledJob("taxonomy", _taxonomy_interval_seconds, _check_taxonomy))
if config.DEDUP_MODE_ENABLED:
    _shared_jobs.append(_ScheduledJob("dedup", _dedup_interval_seconds, _check_dedup))
_shared_jobs.extend(
    [
        _ScheduledJob("backup", _backup_interval_seconds, _check_backup),
        _ScheduledJob(
            "proposal_cleanup",
            _proposal_cleanup_interval_seconds,
            _check_proposal_cleanup,
        ),
    ]
)
_SHARED_JOBS = tuple(_shared_jobs)


def _job_due(job: _ScheduledJob, now: datetime) -> bool:
    if job.name == "backup":
        latest_backup = backup_service.get_latest_backup_datetime()
        if latest_backup is None:
            return True
        return now >= latest_backup + timedelta(seconds=job.interval_seconds())

    state_row = db.get_scheduler_state(job.name)
    if not state_row or not state_row.get("last_run_at"):
        return True

    last_run = db._parse_datetime(state_row["last_run_at"])
    if last_run is None:
        return True

    return now >= last_run + timedelta(seconds=job.interval_seconds())


async def _run_job(job: _ScheduledJob, now: datetime, *, owner_label: str | None = None) -> None:
    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
    previous = db.get_scheduler_state(job.name) or {}
    log_parts = [f"name={job.name}"]
    if owner_label:
        log_parts.append(f"owner={owner_label}")
    logger.info("scheduler.job.start %s", " ".join(log_parts))

    try:
        result = job.runner()
        if inspect.isawaitable(result):
            await result
        db.upsert_scheduler_state(
            job.name,
            last_run_at=now_iso,
            last_success_at=now_iso,
            last_error=None,
        )
        logger.info("scheduler.job.complete %s", " ".join(log_parts))
    except Exception as exc:
        db.upsert_scheduler_state(
            job.name,
            last_run_at=now_iso,
            last_success_at=previous.get("last_success_at"),
            last_error=str(exc),
        )
        logger.error(
            "scheduler.job.error %s error=%s",
            " ".join(log_parts),
            exc,
            exc_info=True,
        )


async def _run_due_jobs(
    jobs: tuple[_ScheduledJob, ...],
    now: datetime,
    *,
    owner_label: str,
) -> None:
    for job in jobs:
        if not _job_due(job, now):
            continue
        await _run_job(job, now, owner_label=owner_label)


async def _review_loop() -> None:
    if _bot is None:
        return

    await _bot.wait_until_ready()
    logger.info(
        "Scheduler review loop ready. Reviews every %smin.",
        config.REVIEW_CHECK_INTERVAL_MINUTES,
    )

    if _REVIEW_STARTUP_DELAY_SECONDS > 0:
        await asyncio.sleep(_REVIEW_STARTUP_DELAY_SECONDS)

    try:
        while not _bot.is_closed():
            now = datetime.now()
            if _job_due(_REVIEW_JOB, now):
                await _run_job(_REVIEW_JOB, now, owner_label="bot")
            await asyncio.sleep(_TICK_SECONDS)
    except asyncio.CancelledError:
        raise


async def _shared_loop(owner_label: str) -> None:
    owns_lock = False
    logger.info(
        (
            "Scheduler shared loop online. owner=%s maintenance=%s "
            "taxonomy=%sh dedup=%sh backup=%sh cleanup=%sh."
        ),
        owner_label,
        (
            f"{config.MAINTENANCE_INTERVAL_HOURS}h"
            if config.MAINTENANCE_MODE_ENABLED
            else "disabled"
        ),
        config.TAXONOMY_INTERVAL_HOURS,
        f"{config.DEDUP_INTERVAL_HOURS}h" if config.DEDUP_MODE_ENABLED else "disabled",
        config.BACKUP_INTERVAL_HOURS,
        config.PROPOSAL_CLEANUP_INTERVAL_HOURS,
    )

    try:
        while True:
            now = datetime.now()
            now_iso = now.strftime("%Y-%m-%d %H:%M:%S")

            if not owns_lock:
                owns_lock = db.acquire_scheduler_owner(
                    _owner_pid,
                    owner_label,
                    stale_seconds=_OWNER_STALE_SECONDS,
                    now=now_iso,
                )
                if owns_lock:
                    logger.info(
                        "scheduler.owner.acquired pid=%s owner=%s",
                        _owner_pid,
                        owner_label,
                    )
                else:
                    await asyncio.sleep(_TICK_SECONDS)
                    continue
            elif not db.heartbeat_scheduler_owner(_owner_pid, now=now_iso):
                owns_lock = False
                logger.warning(
                    "scheduler.owner.lost pid=%s owner=%s",
                    _owner_pid,
                    owner_label,
                )
                await asyncio.sleep(_TICK_SECONDS)
                continue

            await _run_due_jobs(_SHARED_JOBS, now, owner_label=owner_label)
            await asyncio.sleep(_TICK_SECONDS)
    except asyncio.CancelledError:
        raise
    finally:
        if owns_lock:
            db.release_scheduler_owner(_owner_pid)
            logger.info(
                "scheduler.owner.released pid=%s owner=%s",
                _owner_pid,
                owner_label,
            )


def start(bot=None, auth_user_id: int | None = None, *, owner_label: str = "bot"):
    """Start bot review scheduling and the shared background scheduler.

    Review checks stay bot-owned because they require Discord delivery.
    Maintenance-style jobs use a DB-backed owner lock so either the bot or
    API process can host them without double-running.
    """
    global _bot, _authorized_user_id, _review_task, _shared_task

    loop = asyncio.get_running_loop()

    if bot is not None and auth_user_id:
        _bot = bot
        _authorized_user_id = auth_user_id
        if _review_task is None or _review_task.done():
            _review_task = loop.create_task(_review_loop(), name="learn-review-scheduler")

    if _shared_task is None or _shared_task.done():
        _shared_task = loop.create_task(
            _shared_loop(owner_label),
            name=f"learn-shared-scheduler-{owner_label}",
        )

    return _shared_task


def stop() -> None:
    """Stop all scheduler tasks owned by this process."""
    global _review_task, _shared_task

    db.release_scheduler_owner(_owner_pid)

    for task in (_review_task, _shared_task):
        if task is not None and not task.done():
            task.cancel()

    _review_task = None
    _shared_task = None
