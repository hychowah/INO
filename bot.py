#!/usr/bin/env python3
"""
Learning Agent Discord Bot — standalone entry point.
=====================================================
A separate bot from the kimi bridge, dedicated to learning & spaced repetition.
All LLM logic lives in AGENTS.md; DB primitives in db.py/tools.py.
This file: create bot, wire events, session routing, start.
"""

import sys
import io
import logging
import asyncio
from datetime import datetime

# Fix Windows console encoding before anything else
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("discord").setLevel(logging.INFO)
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("bot")

import discord
from discord.ext import commands

import config
import db
from services import pipeline, scheduler, state
from services.parser import parse_llm_response
from services.views import AddConceptConfirmView, QuizNavigationView
from services.formatting import truncate_with_suffix

# ============================================================================
# PENDING ADD-CONCEPT TRACKING
# ============================================================================

# Maps message_id → (action_data, AddConceptConfirmView) for reply-to detection
_pending_concepts: dict[int, tuple[dict, AddConceptConfirmView]] = {}

_AFFIRMATIVES = {'yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'y', 'add',
                 'add it', 'go ahead', 'do it', 'please', 'yea'}
_NEGATIVES = {'no', 'nah', 'nope', 'skip', 'n', 'no thanks', 'pass',
              'decline', "don't", 'dont'}


def _is_affirmative(text: str) -> bool:
    text = text.lower().strip().rstrip('.!,')
    return text in _AFFIRMATIVES or text.startswith(('yes', 'sure', 'add'))


def _is_negative(text: str) -> bool:
    text = text.lower().strip().rstrip('.!,')
    return text in _NEGATIVES or text.startswith(('no ', 'nah', 'skip'))


# ============================================================================
# BOT SETUP
# ============================================================================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)
bot._restart_requested = False

# ============================================================================
# STATE
# ============================================================================

_db_initialized = False


# ============================================================================
# SECURITY
# ============================================================================

def authorized_only():
    """Decorator to restrict commands to the authorized user."""
    async def predicate(ctx):
        uid = ctx.author.id if hasattr(ctx, "author") else ctx.user.id
        if uid != config.AUTHORIZED_USER_ID:
            await ctx.send("You are not authorized to use this bot.")
            logger.warning(f"Unauthorized access attempt by {uid}")
            return False
        return True
    return commands.check(predicate)


# ============================================================================
# HELPERS
# ============================================================================

async def send_long(ctx, text: str, title: str = "Learn"):
    """Send text to Discord, handling length limits."""
    is_interaction = ctx.interaction is not None

    if not text or not text.strip():
        text = "(empty response)"

    if len(text) <= config.MAX_MESSAGE_LENGTH:
        if is_interaction:
            await ctx.interaction.followup.send(text)
        else:
            await ctx.send(text)
        return

    # Split into chunks
    chunks = [text[i:i + config.MAX_MESSAGE_LENGTH]
              for i in range(0, len(text), config.MAX_MESSAGE_LENGTH)]

    for i, chunk in enumerate(chunks):
        if is_interaction:
            await ctx.interaction.followup.send(chunk)
        else:
            await ctx.send(chunk)


# ============================================================================
# COMMANDS
# ============================================================================

@bot.hybrid_command(
    name="learn",
    description="AI learning coach — ask questions, get quizzed, track knowledge",
)
@authorized_only()
async def learn_command(ctx, *, text: str = ""):
    """
    /learn why is stainless steel rust-proof?
    /learn quiz me on material science
    Also works: just type plain messages without /learn.
    """
    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    try:
        async with ctx.channel.typing():
            response, pending_action, assess_meta = await _handle_user_message(
                text or "hello", str(ctx.author))

        if pending_action:
            view = AddConceptConfirmView(pending_action)
            if is_interaction:
                sent = await ctx.interaction.followup.send(
                    response[:config.MAX_MESSAGE_LENGTH], view=view)
            else:
                sent = await ctx.send(response[:config.MAX_MESSAGE_LENGTH], view=view)
            _pending_concepts[sent.id] = (pending_action, view)
            view.on_resolved = lambda mid=sent.id: _pending_concepts.pop(mid, None)
        elif assess_meta:
            view = QuizNavigationView(
                concept_id=assess_meta['concept_id'],
                quality=assess_meta['quality'],
                message_handler=_handle_user_message,
            )
            if is_interaction:
                await ctx.interaction.followup.send(
                    response[:config.MAX_MESSAGE_LENGTH], view=view)
            else:
                await ctx.send(response[:config.MAX_MESSAGE_LENGTH], view=view)
        else:
            await send_long(ctx, response)
    except Exception as e:
        logger.error(f"learn_command error: {e}", exc_info=True)
        msg = f"Error: `{e}`"
        if is_interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)


@bot.hybrid_command(name="ping", description="Check bot is alive")
async def ping_command(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"Pong! ({latency}ms)")


@bot.hybrid_command(name="sync", description="Sync slash commands")
@authorized_only()
async def sync_command(ctx):
    synced = await bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} command(s).")


@bot.hybrid_command(
    name="persona",
    description="View or switch persona preset (mentor/coach/buddy)",
)
@authorized_only()
async def persona_command(ctx, *, name: str = ""):
    """
    /persona          — show current persona + available presets
    /persona mentor   — switch to the Mentor persona
    /persona coach    — switch to the Coach persona
    /persona buddy    — switch to the Buddy persona
    """
    _ensure_db()
    current = db.get_persona()
    available = db.get_available_personas()

    if not name.strip():
        # Show current + list
        icons = {"mentor": "🎓", "coach": "🏋️", "buddy": "🤝"}
        descriptions = {
            "mentor": "Calm, wise senior colleague — guides via questions, dry wit, measured enthusiasm",
            "coach": "Direct, results-oriented trainer — blunt feedback, action items, structured",
            "buddy": "Enthusiastic friend — casual, playful, analogies, celebrates wins loudly",
        }
        lines = [f"**Active persona:** {icons.get(current, '🎭')} **{current.title()}**\n"]
        lines.append("**Available presets:**")
        for p in available:
            icon = icons.get(p, "🎭")
            desc = descriptions.get(p, "")
            marker = " ← active" if p == current else ""
            lines.append(f"{icon} **{p.title()}** — {desc}{marker}")
        lines.append(f"\nSwitch with: `/persona <name>`")
        await send_long(ctx, "\n".join(lines))
        return

    # Switch persona
    target = name.strip().lower()
    if target == current:
        await ctx.send(f"Already using **{current.title()}** persona.")
        return

    try:
        db.set_persona(target)
    except ValueError:
        await ctx.send(
            f"Unknown persona `{target}`. Available: {', '.join(available)}"
        )
        return

    # Invalidate prompt cache + conversation session so new persona takes effect
    pipeline.invalidate_prompt_cache()
    pipeline.reset_conversation_session()

    icons = {"mentor": "🎓", "coach": "🏋️", "buddy": "🤝"}
    icon = icons.get(target, "🎭")
    await ctx.send(f"{icon} Switched to **{target.title()}** persona. Next message will use the new style.")


# ============================================================================
# FAST-PATH COMMANDS (local DB reads, no LLM call)
# ============================================================================

@bot.hybrid_command(name="due", description="Show concepts due for review")
@authorized_only()
async def due_command(ctx):
    """Show due concepts and review stats without calling kimi-cli."""
    _ensure_db()
    stats = db.get_review_stats()
    due = db.get_due_concepts(limit=10)

    lines = [f"📊 **{stats['due_now']}** due | **{stats['total_concepts']}** concepts | "
             f"avg score **{stats['avg_mastery']}/100** | "
             f"**{stats['reviews_last_7d']}** reviews this week\n"]

    if due:
        lines.append("**Due for review:**")
        for c in due:
            remark = c.get('latest_remark', '')
            remark_str = f"\n  └ _{remark[:80]}_" if remark else ""
            lines.append(
                f"• [concept:{c['id']}] **{c['title']}** — score {c['mastery_level']}/100, "
                f"interval {c['interval_days']}d{remark_str}"
            )
    else:
        lines.append("✅ Nothing due right now!")

    await send_long(ctx, "\n".join(lines))


@bot.hybrid_command(name="topics", description="Show your knowledge map")
@authorized_only()
async def topics_command(ctx):
    """Show the topic tree with mastery stats, no LLM call."""
    _ensure_db()
    from services.tools import _handle_list_topics
    msg_type, result = _handle_list_topics({})
    await send_long(ctx, result)


@bot.hybrid_command(name="clear", description="Clear chat history")
@authorized_only()
async def clear_command(ctx):
    """Clear learning agent chat history."""
    _ensure_db()
    db.clear_chat_history()
    await ctx.send("🗑️ Chat history cleared.")


@bot.hybrid_command(
    name="maintain",
    description="Run maintenance + dedup check now",
)
@authorized_only()
async def maintain_command(ctx):
    """Manually trigger maintenance diagnostics and dedup agent."""
    from services.dedup import format_dedup_suggestions
    from services.views import DedupConfirmView, MaintenanceConfirmView

    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    _ensure_db()
    parts = []

    # 1. Maintenance diagnostics
    proposed_actions = []
    try:
        maint_context = pipeline.handle_maintenance()
        if maint_context:
            async with ctx.channel.typing():
                result, proposed_actions = await pipeline.call_maintenance_loop(maint_context)
                msg = result
                for pfx in ("REPLY: ", "REPLY:"):
                    if msg.startswith(pfx):
                        msg = msg[len(pfx):]
                if msg.strip():
                    parts.append(f"🔧 **Maintenance**\n{msg.strip()}")
        else:
            parts.append("🔧 **Maintenance** — no issues found ✅")
    except Exception as e:
        logger.error(f"maintain_command maint error: {e}", exc_info=True)
        parts.append(f"🔧 **Maintenance** — error: `{e}`")

    # 2. Dedup agent (proposal-only)
    try:
        # Skip if there's already a pending dedup proposal
        existing = db.get_pending_proposal('dedup')
        if existing:
            parts.append("🔄 **Dedup** — pending proposal already exists, check your DMs")
        else:
            async with ctx.channel.typing():
                groups = await pipeline.handle_dedup_check()
            if groups:
                proposal_id = db.save_proposal('dedup', groups)
                suggestion_text = format_dedup_suggestions(groups)
                view = DedupConfirmView(proposal_id, groups)
                parts.append(suggestion_text)
                # We'll send the view with the main message below
            else:
                groups = None
                parts.append("🔄 **Dedup** — no duplicates found ✅")
    except Exception as e:
        logger.error(f"maintain_command dedup error: {e}", exc_info=True)
        parts.append(f"🔄 **Dedup** — error: `{e}`")
        groups = None

    # Send the main response
    main_text = "\n\n".join(parts)

    # Determine which views to attach
    views_to_send = []
    if groups:
        views_to_send.append(('dedup', view))
    if proposed_actions:
        maint_proposal_id = db.save_proposal('maintenance', proposed_actions)
        maint_view = MaintenanceConfirmView(
            maint_proposal_id, proposed_actions,
            pipeline.execute_maintenance_actions,
        )
        views_to_send.append(('maintenance', maint_view))

    if views_to_send:
        # Send main text first, then each view as separate message
        await send_long(ctx, main_text)
        for label, v in views_to_send:
            if is_interaction:
                await ctx.interaction.followup.send(
                    content=f"👆 **Approve/reject {label} actions above:**",
                    view=v,
                )
            else:
                await ctx.send(
                    content=f"👆 **Approve/reject {label} actions above:**",
                    view=v,
                )
    else:
        await send_long(ctx, main_text)


@bot.hybrid_command(
    name="review",
    description="Pull your next due review quiz",
)
@authorized_only()
async def review_command(ctx):
    """Manually trigger a review quiz for the next due concept."""
    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)
    else:
        await ctx.typing()

    _ensure_db()

    review_lines = pipeline.handle_review_check()
    if not review_lines:
        msg = "✅ No concepts to review — add some topics first!"
        if is_interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)
        return

    payload = review_lines[0]
    try:
        review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"
        async with ctx.channel.typing():
            response, _pending, assess_meta = await _handle_user_message(
                review_text, str(ctx.author))

        if not response or not response.strip():
            response = "Could not generate a review quiz. Try again?"
        else:
            response = f"📚 **Learning Review**\n{response}"

        if assess_meta:
            view = QuizNavigationView(
                concept_id=assess_meta['concept_id'],
                quality=assess_meta['quality'],
                message_handler=_handle_user_message,
            )
            if is_interaction:
                await ctx.interaction.followup.send(
                    response[:config.MAX_MESSAGE_LENGTH], view=view)
            else:
                await ctx.send(response[:config.MAX_MESSAGE_LENGTH], view=view)
        else:
            await send_long(ctx, response)
    except Exception as e:
        logger.error(f"review_command error: {e}", exc_info=True)
        msg = f"Error: `{e}`"
        if is_interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)


def _ensure_db():
    """Ensure DB is initialized (idempotent)."""
    global _db_initialized
    if not _db_initialized:
        pipeline.init_databases()
        _db_initialized = True


# ============================================================================
# CORE HANDLER
# ============================================================================

async def _handle_user_message(text: str, author: str) -> tuple[str, dict | None, dict | None]:
    """Core handler: text in → (response, pending_action | None, assess_meta | None).

    If the LLM wants to add_concept (and this is not a button callback),
    the action is NOT executed — raw action_data is returned so the caller
    can attach an AddConceptConfirmView.

    If the action was a successful assess, assess_meta is returned with
    concept_id and quality so the caller can attach QuizNavigationView.
    """
    _ensure_db()
    state.last_activity_at = datetime.now()

    # Set action source for audit trail
    from services.tools import set_action_source
    set_action_source('discord')

    # Full pipeline: context → LLM (+ fetch loop)
    llm_response = await pipeline.call_with_fetch_loop(
        "command", text, author
    )

    # --- intercept add_concept before execution (skip for button callbacks) ---
    prefix, message, action_data = parse_llm_response(llm_response)
    if (action_data
            and action_data.get('action', '').lower().strip() == 'add_concept'
            and not text.startswith('[BUTTON]')):
        # Save chat history (message only, concept not created yet)
        if text:
            db.add_chat_message('user', text)
        display_msg = action_data.get('message', message or '')
        if display_msg:
            db.add_chat_message('assistant', display_msg)
        logger.info(f"Intercepted add_concept — pending user confirmation")
        return display_msg, action_data, None

    # All other actions: execute normally
    final_result = await pipeline.execute_llm_response(text, llm_response, "command")

    logger.debug(f"Agent result: {final_result[:500]!r}")

    msg_type, msg = pipeline.process_output(final_result)
    logger.info(f"Completed: '{text[:50]}' → {msg_type}")

    # Detect successful assess → populate metadata for QuizNavigationView
    assess_meta = None
    if (action_data
            and action_data.get('action', '').lower().strip() == 'assess'
            and '⚠️' not in (msg or '')):
        cid = db.get_session('last_assess_concept_id')
        quality = db.get_session('last_assess_quality')
        if cid and quality:
            assess_meta = {
                'concept_id': int(cid),
                'quality': int(quality),
            }

    return msg, None, assess_meta


# ============================================================================
# EVENTS
# ============================================================================

@bot.event
async def on_ready():
    logger.info("=" * 50)
    logger.info("Learning Agent Bot is ONLINE!")
    logger.info("=" * 50)
    logger.info(f"Bot: {bot.user.name} ({bot.user.id})")
    logger.info(f"Guilds: {len(bot.guilds)}")
    config.print_config()
    logger.info("Commands: /learn /due /topics /review /persona /clear /ping /sync (or !prefix)")
    logger.info("=" * 50)

    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync: {e}")

    # Start review scheduler
    scheduler.start(bot, config.AUTHORIZED_USER_ID)
    logger.info("[SCHEDULER] Review check started")

    # Start web UI in a background thread
    try:
        import threading
        import webui.server as webui_server
        webui_thread = threading.Thread(
            target=webui_server.main, kwargs={"skip_init": True}, daemon=True
        )
        webui_thread.start()
        logger.info(f"[WEBUI] Started on http://localhost:{webui_server.PORT}")
    except Exception as e:
        logger.error(f"[WEBUI] Failed to start: {e}", exc_info=True)

    # Heartbeat
    bot.loop.create_task(_heartbeat())


async def _heartbeat():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(300)
        latency_ms = round(bot.latency * 1000)
        logger.info(f"[HEARTBEAT] alive | latency={latency_ms}ms")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CheckFailure, commands.CommandNotFound)):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await _safe_send(ctx, f"Missing argument: `{error.param.name}`")
        return
    logger.error(f"Command error: {type(error).__name__}: {error}")
    await _safe_send(ctx, f"Error: `{type(error).__name__}`")


async def _safe_send(ctx, text: str):
    """Send a message, handling deferred interactions gracefully."""
    try:
        if ctx.interaction and ctx.interaction.response.is_done():
            await ctx.interaction.followup.send(text)
        else:
            await ctx.send(text)
    except discord.errors.NotFound:
        # Interaction expired — nothing we can do
        logger.warning("Could not send error message: interaction expired")


@bot.event
async def on_message(message):
    """Every message from the authorized user goes through the learning pipeline."""
    if message.author.bot:
        await bot.process_commands(message)
        return

    if message.author.id != config.AUTHORIZED_USER_ID:
        await bot.process_commands(message)
        return

    # Prefix commands (!) and slash commands always handled first
    if message.content.startswith(("!", "/")):
        await bot.process_commands(message)
        return

    text = message.content.strip()
    if not text:
        await bot.process_commands(message)
        return

    # Check for reply to a pending add-concept message
    if message.reference and message.reference.message_id in _pending_concepts:
        action_data, view = _pending_concepts[message.reference.message_id]
        if not view.decided:
            reply_text = text.lower().strip()
            if _is_affirmative(reply_text):
                view.decided = True
                view._disable_all()
                from services.tools import execute_action
                msg_type, result = execute_action(
                    action_data.get('action', 'add_concept'),
                    action_data.get('params', {}),
                )
                note = f"\n\n⚠️ Could not add concept: {result}" if msg_type == 'error' \
                    else f"\n\n✅ {result}"
                if msg_type != 'error':
                    # Persist confirmation to chat history so the LLM sees the
                    # concept_id on subsequent turns
                    db.add_chat_message('user', '[confirmed: add concept]')
                    db.add_chat_message('assistant', f"✅ {result}")
                try:
                    orig = await message.channel.fetch_message(message.reference.message_id)
                    await orig.edit(
                        content=truncate_with_suffix(orig.content or '', note),
                        view=view)
                except discord.errors.NotFound:
                    pass
                _pending_concepts.pop(message.reference.message_id, None)
                await message.add_reaction('✅')
                return
            elif _is_negative(reply_text):
                view.decided = True
                view._disable_all()
                # Record decline so the LLM doesn't re-suggest the same concept
                db.add_chat_message('user', '[declined: add concept]')
                try:
                    orig = await message.channel.fetch_message(message.reference.message_id)
                    await orig.edit(view=view)
                except discord.errors.NotFound:
                    pass
                _pending_concepts.pop(message.reference.message_id, None)
                await message.add_reaction('👍')
                return
            # Ambiguous reply — fall through to normal pipeline

    # Route every plain message through the learning pipeline
    try:
        async with message.channel.typing():
            response, pending_action, assess_meta = await _handle_user_message(
                text, str(message.author))

        if not response or not response.strip():
            response = "(empty response)"

        if pending_action:
            # Show educational answer + confirmation buttons
            view = AddConceptConfirmView(pending_action)
            sent = await message.reply(response[:config.MAX_MESSAGE_LENGTH], view=view)
            _pending_concepts[sent.id] = (pending_action, view)
            view.on_resolved = lambda mid=sent.id: _pending_concepts.pop(mid, None)
        elif assess_meta:
            # Show assessment feedback + quiz navigation buttons
            view = QuizNavigationView(
                concept_id=assess_meta['concept_id'],
                quality=assess_meta['quality'],
                message_handler=_handle_user_message,
            )
            await message.reply(response[:config.MAX_MESSAGE_LENGTH], view=view)
        else:
            # Send, handling Discord's 2000-char limit
            while response:
                chunk = response[:config.MAX_MESSAGE_LENGTH]
                response = response[config.MAX_MESSAGE_LENGTH:]
                await message.reply(chunk)

    except Exception as e:
        logger.error(f"Message handler error: {e}", exc_info=True)
        await message.reply(f"Error: `{e}`")

    # Don't call process_commands — plain text is fully handled above


# ============================================================================
# MAIN
# ============================================================================

def main():
    errors = config.validate_config()
    if errors:
        logger.error("CONFIGURATION ERRORS:")
        for e in errors:
            logger.error(f"  * {e}")
        sys.exit(1)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Starting learning bot... data dir: {config.DATA_DIR}")

    try:
        bot.run(config.BOT_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.critical("Invalid Bot Token!")
    except Exception as e:
        logger.critical(f"Fatal: {e}", exc_info=True)

    if getattr(bot, "_restart_requested", False):
        logger.info("Clean exit with code 42 — start.bat will restart.")
        sys.exit(42)


if __name__ == "__main__":
    main()
