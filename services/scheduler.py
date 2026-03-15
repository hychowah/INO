"""
Learning review scheduler — background task that checks for due reviews
every N minutes and sends Discord DMs with quiz questions.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import discord

import config
import db
from services import pipeline
from services.dedup import format_dedup_suggestions
from services.views import DedupConfirmView

logger = logging.getLogger("scheduler")

# Module-level state set by start()
_bot = None
_authorized_user_id = None

# Cooldown tracking: {concept_id: datetime_last_sent}
_review_sent_at: dict[int, datetime] = {}


async def _check_reviews():
    """Check for due concepts and send review quizzes via DM.
    Suppressed if user has been active within SESSION_TIMEOUT_MINUTES."""
    # Suppress during active session to avoid interrupting conversation
    from services.state import last_activity_at
    if last_activity_at:
        cutoff = datetime.now() - timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)
        if last_activity_at > cutoff:
            logger.debug("Skipping review check — user active in session")
            return

    logger.debug("Running review-check...")
    try:
        # Direct call — no subprocess
        review_lines = pipeline.handle_review_check()

        if not review_lines:
            logger.debug("No pending reviews")
            return

        cooldown = timedelta(hours=config.REVIEW_NAG_COOLDOWN_HOURS)
        now = datetime.now()

        for line in review_lines:
            # Extract concept_id from "id|context" format
            try:
                cid = int(line.split("|", 1)[0])
            except (ValueError, IndexError):
                cid = None

            if cid and cid in _review_sent_at:
                if now - _review_sent_at[cid] < cooldown:
                    logger.debug(f"Skipping concept #{cid} — sent within cooldown")
                    continue

            logger.info(f"Review due: {line[:80]}")
            await _send_review_quiz(line)

    except Exception as e:
        logger.error(f"Error in review-check: {e}", exc_info=True)


async def _send_review_quiz(payload: str):
    """
    Send a review quiz DM.
    payload format: concept_id|context_string

    Uses kimi-cli via the pipeline to generate a question,
    then DMs it and activates the chat session.
    """
    if not _bot or not _authorized_user_id:
        logger.error("Bot not initialized, can't send review")
        return

    try:
        user = await _bot.fetch_user(_authorized_user_id)
        if not user:
            logger.error(f"Could not find user {_authorized_user_id}")
            return

        try:
            review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"
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
                await user.send(f"📚 **Learning Review**\n{message}")
                logger.info("Sent review DM")
                # Track cooldown
                try:
                    cid = int(payload.split("|", 1)[0])
                    _review_sent_at[cid] = datetime.now()
                except (ValueError, IndexError):
                    pass
            else:
                logger.debug("Empty result for review quiz")

        except ImportError as ie:
            logger.error(f"Import error: {ie}")
            await user.send(f"📚 **Learning Review** — Time to review:\n{payload}")

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
