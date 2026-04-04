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
import json
import logging
from datetime import datetime, timedelta

import discord

import config
import db
from bot.messages import send_review_question
from services import pipeline
from services.dedup import format_dedup_suggestions
from services.views import DedupConfirmView
from services.formatting import truncate_for_discord

logger = logging.getLogger("scheduler")

# Module-level state set by start()
_bot = None
_authorized_user_id = None


# ============================================================================
# Pending review helpers
# ============================================================================

def _get_pending_review() -> dict | None:
    """Read pending review blob from session state. Returns dict or None."""
    raw = db.get_session('pending_review')
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt pending_review in session state — clearing")
        db.set_session('pending_review', None)
        return None


def _set_pending_review(concept_id: int, concept_title: str,
                        question: str) -> None:
    """Write a new pending review blob. Called AFTER DM is confirmed sent."""
    blob = {
        'concept_id': concept_id,
        'concept_title': concept_title,
        'question': question,
        'sent_at': datetime.now().isoformat(),
        'reminder_count': 0,
    }
    db.set_session('pending_review', json.dumps(blob))
    logger.debug(f"Set pending review: concept #{concept_id}")


def _update_pending_reminder(pending: dict) -> None:
    """Increment reminder count + reset sent_at after sending a reminder."""
    pending['reminder_count'] = pending.get('reminder_count', 0) + 1
    pending['sent_at'] = datetime.now().isoformat()
    db.set_session('pending_review', json.dumps(pending))


def _clear_pending_review() -> None:
    """Clear pending review state (max reminders exhausted or concept deleted)."""
    db.set_session('pending_review', None)
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
    # Suppress during active session to avoid interrupting conversation
    from services.state import last_activity_at
    if last_activity_at:
        cutoff = datetime.now() - timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)
        if last_activity_at > cutoff:
            logger.debug("Skipping review check — user active in session")
            return

    logger.debug("Running review-check...")

    # Suppress if /review command is actively generating a quiz
    if db.get_session('review_in_progress'):
        logger.debug("Skipping review check — /review command in progress")
        return

    # --- Handle pending (unanswered) review ---
    pending = _get_pending_review()
    if pending:
        cid = pending.get('concept_id')
        title = pending.get('concept_title', 'Unknown')

        # Guard: concept might have been deleted while pending
        if cid and not db.get_concept(cid):
            logger.info(f"Pending concept #{cid} no longer exists — clearing")
            _clear_pending_review()
            # Fall through to normal flow below
        else:
            # Check cooldown since last send/reminder
            sent_at_str = pending.get('sent_at', '')
            try:
                sent_at = datetime.fromisoformat(sent_at_str)
            except (ValueError, TypeError):
                sent_at = datetime.now()

            cooldown = timedelta(hours=config.REVIEW_NAG_COOLDOWN_HOURS)
            elapsed = datetime.now() - sent_at

            if elapsed < cooldown:
                logger.debug(
                    f"Pending review #{cid} — {elapsed.total_seconds()/3600:.1f}h "
                    f"< {config.REVIEW_NAG_COOLDOWN_HOURS}h cooldown, skipping"
                )
                return

            # Cooldown expired — check reminder count
            reminder_count = pending.get('reminder_count', 0)
            max_reminders = getattr(config, 'REVIEW_REMINDER_MAX', 3)

            if reminder_count >= max_reminders:
                logger.info(
                    f"Pending review #{cid} — {reminder_count} reminders sent, "
                    f"giving up and moving to next concept"
                )
                _clear_pending_review()
                # Fall through to normal flow below
            else:
                # Send a static reminder (no LLM call)
                await _send_review_reminder(pending)
                return

    # --- Normal flow: pick next due concept and send LLM-generated quiz ---
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

    cid = pending.get('concept_id')
    title = pending.get('concept_title', 'Unknown')
    reminder_count = pending.get('reminder_count', 0) + 1
    max_reminders = getattr(config, 'REVIEW_REMINDER_MAX', 3)
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
        db.set_session('active_concept_id', str(cid))
        db.set_session('quiz_anchor_concept_id', str(cid))

        # Update pending state (increment counter, reset timer)
        _update_pending_reminder(pending)

    except discord.Forbidden:
        logger.error("Cannot send DM (forbidden)")
    except Exception as e:
        logger.error(f"Error sending review reminder: {e}", exc_info=True)


async def _send_review_quiz(payload: str):
    """
    Send a review quiz DM using the two-prompt pipeline.
    payload format: concept_id|context_string

    Prompt 1 (reasoning model): Generates the optimal question from pre-loaded data.
    Prompt 2 (fast model): Packages it with persona voice and action JSON format.
    Falls back to single-prompt flow if the two-prompt pipeline fails.
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
            set_action_source('scheduler')

            # Set active concept for subsequent assess action
            if cid:
                db.set_session('active_concept_id', str(cid))
                db.set_session('quiz_anchor_concept_id', str(cid))

            review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"

            # --- Two-prompt pipeline (with fallback) ---
            from services.llm import LLMError
            try:
                if cid:
                    p1_result = await pipeline.generate_quiz_question(cid)
                    llm_response = await pipeline.package_quiz_for_discord(
                        p1_result, cid
                    )
                else:
                    raise LLMError("No concept_id in payload", retryable=True)
            except LLMError as e:
                logger.warning(
                    f"Two-prompt pipeline failed ({e}), "
                    f"falling back to single-prompt flow"
                )
                llm_response = await pipeline.call_with_fetch_loop(
                    mode="reply",
                    text=review_text,
                    author=str(_authorized_user_id),
                )

            # Parse action JSON and extract human-readable message
            final_result = await pipeline.execute_llm_response(
                review_text, llm_response, "reply"
            )
            _msg_type, message = pipeline.process_output(final_result)

            if message and message.strip():
                # Store the actual question text for accurate review logging
                db.set_session('last_quiz_question', message.strip())
                from bot.handler import _handle_user_message
                await send_review_question(user.send, message, cid, _handle_user_message)
                logger.info("Sent review DM")

                # Set pending review state AFTER DM is confirmed sent.
                # This avoids the race condition where pending is set
                # during the LLM await but the user answers a previous
                # quiz in the meantime.
                if cid:
                    concept = db.get_concept(cid)
                    concept_title = concept['title'] if concept else 'Unknown'
                    _set_pending_review(cid, concept_title, message[:500])
            else:
                logger.debug("Empty result for review quiz")

        except ImportError as ie:
            logger.error(f"Import error: {ie}")
            await user.send(truncate_for_discord(
                f"📚 **Learning Review** — Time to review:\n{payload}"))

    except discord.Forbidden:
        logger.error("Cannot send DM (forbidden)")
    except Exception as e:
        logger.error(f"Error sending review: {e}", exc_info=True)


async def _check_maintenance():
    """Run DB diagnostics and send maintenance report if issues found."""
    logger.debug("Running maintenance check...")
    try:
        # Direct call — no subprocess
        diagnostic_context = pipeline.handle_maintenance()

        if not diagnostic_context:
            logger.debug("Maintenance: no issues found")
            return

        logger.info(f"Maintenance issues found, sending to LLM for triage")
        await _send_maintenance_report(diagnostic_context)

    except Exception as e:
        logger.error(f"Error in maintenance check: {e}", exc_info=True)


async def _send_maintenance_report(diagnostic_context: str):
    """Send diagnostic context to the LLM for triage, then DM the report.
    Safe actions are executed immediately; destructive actions are proposed
    with Discord buttons for user approval."""
    from services.views import MaintenanceConfirmView

    if not _bot or not _authorized_user_id:
        logger.error("Bot not initialized, can't send maintenance report")
        return

    try:
        user = await _bot.fetch_user(_authorized_user_id)
        if not user:
            logger.error(f"Could not find user {_authorized_user_id}")
            return

        try:
            # Let the LLM triage and fix issues (multi-action loop)
            final_result, proposed_actions = await pipeline.call_maintenance_loop(
                diagnostic_context
            )

            if final_result and final_result.strip():
                # Strip REPLY: prefix
                msg = final_result
                if msg.startswith("REPLY: "):
                    msg = msg[7:]
                elif msg.startswith("REPLY:"):
                    msg = msg[6:]

                if msg.strip():
                    await user.send(f"🔧 **Knowledge Base Maintenance**\n\n{msg[:1900]}")
                    logger.info("Sent maintenance report DM")

            # If there are proposed destructive actions, send with buttons
            if proposed_actions:
                proposal_id = db.save_proposal('maintenance', proposed_actions)
                view = MaintenanceConfirmView(
                    proposal_id, proposed_actions,
                    pipeline.execute_maintenance_actions,
                )
                # Format proposed actions for the DM
                action_lines = []
                for i, a in enumerate(proposed_actions, 1):
                    name = a.get('action', 'unknown')
                    desc = a.get('message', '')[:80]
                    action_lines.append(f"**{i}.** `{name}` — {desc}")

                proposal_text = (
                    "⏳ **Actions needing your approval:**\n\n"
                    + "\n".join(action_lines)
                    + "\n\nUse the buttons below to approve or reject."
                )
                sent_msg = await user.send(content=proposal_text[:1900], view=view)
                db.update_proposal_message_id(proposal_id, sent_msg.id)
                logger.info(f"Sent {len(proposed_actions)} proposed maintenance actions")

        except ImportError as ie:
            logger.error(f"Import error in maintenance: {ie}")
        except Exception as e:
            logger.error(f"Error in maintenance pipeline: {e}", exc_info=True)

    except discord.Forbidden:
        logger.error("Cannot send DM (forbidden)")
    except Exception as e:
        logger.error(f"Error sending maintenance report: {e}", exc_info=True)


async def _check_dedup():
    """Run the dedup sub-agent to find potential duplicates.
    Now proposal-only: stores suggestions in DB and DMs user with buttons."""
    # Skip if there's already a pending dedup proposal
    existing = db.get_pending_proposal('dedup')
    if existing:
        logger.debug("[DEDUP] Skipping — pending proposal exists")
        return

    logger.info("[DEDUP] Running dedup check...")
    try:
        groups = await pipeline.handle_dedup_check()
        if not groups:
            logger.debug("[DEDUP] No duplicates found")
            return

        # Save proposal to DB (survives restarts)
        proposal_id = db.save_proposal('dedup', groups)

        # Send suggestion DM with buttons
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
        logger.info(f"[DEDUP] Sent dedup suggestions ({len(groups)} groups) as proposal #{proposal_id}")

    except Exception as e:
        logger.error(f"Error sending dedup suggestions: {e}", exc_info=True)


async def _loop():
    """Main loop: check for reviews every N minutes, maintenance daily."""
    await _bot.wait_until_ready()
    interval = config.REVIEW_CHECK_INTERVAL_MINUTES
    maint_interval = getattr(config, 'MAINTENANCE_INTERVAL_HOURS', 24)
    logger.info(f"Scheduler ready. Reviews every {interval}min, maintenance every {maint_interval}h.")

    review_cycle = 0
    maint_counter = 0  # counts review cycles; trigger maintenance when enough accumulate
    maint_every_n_cycles = max(1, int((maint_interval * 60) / interval))

    while not _bot.is_closed():
        # Delay first cycle to avoid racing with commands typed at startup
        if review_cycle == 0:
            await asyncio.sleep(30)
        review_cycle += 1
        maint_counter += 1
        logger.debug(f"Review cycle #{review_cycle}")
        try:
            await _check_reviews()
        except Exception as e:
            logger.error(f"Review loop error: {e}", exc_info=True)

        if maint_counter >= maint_every_n_cycles:
            maint_counter = 0
            logger.info("[MAINTENANCE] Running scheduled maintenance check")
            try:
                await _check_maintenance()
            except Exception as e:
                logger.error(f"Maintenance loop error: {e}", exc_info=True)

            # Dedup runs after maintenance on the same schedule
            try:
                await _check_dedup()
            except Exception as e:
                logger.error(f"Dedup loop error: {e}", exc_info=True)

            # Clean up expired proposals
            try:
                db.cleanup_expired_proposals()
            except Exception as e:
                logger.error(f"Proposal cleanup error: {e}", exc_info=True)

        await asyncio.sleep(interval * 60)


def start(bot, auth_user_id):
    """Start the review-check background task."""
    global _bot, _authorized_user_id
    _bot = bot
    _authorized_user_id = auth_user_id
    return bot.loop.create_task(_loop())
