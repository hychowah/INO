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
            response = await _handle_user_message(text or "hello", str(ctx.author))
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
                f"• [{c['id']}] **{c['title']}** — score {c['mastery_level']}/100, "
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
    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    _ensure_db()
    parts = []

    # 1. Maintenance diagnostics
    try:
        maint_context = pipeline.handle_maintenance()
        if maint_context:
            async with ctx.channel.typing():
                result = await pipeline.call_maintenance_loop(maint_context)
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

    # 2. Dedup agent
    try:
        async with ctx.channel.typing():
            groups = await pipeline.handle_dedup_check()
        if groups:
            summaries = await pipeline.execute_dedup_merges(groups)
            if summaries:
                body = "\n".join(f"• {s}" for s in summaries)
                parts.append(f"🔄 **Dedup** — merged {len(summaries)} group(s):\n{body}")
            else:
                parts.append("🔄 **Dedup** — duplicates found but nothing to merge")
        else:
            parts.append("🔄 **Dedup** — no duplicates found ✅")
    except Exception as e:
        logger.error(f"maintain_command dedup error: {e}", exc_info=True)
        parts.append(f"🔄 **Dedup** — error: `{e}`")

    await send_long(ctx, "\n\n".join(parts))


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
        msg = "✅ No concepts due for review right now!"
        if is_interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)
        return

    payload = review_lines[0]
    try:
        review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"
        async with ctx.channel.typing():
            llm_response = await pipeline.call_with_fetch_loop(
                mode="reply",
                text=review_text,
                author=str(ctx.author),
            )

        # Parse action JSON and extract human-readable message
        final_result = await pipeline.execute_llm_response(
            review_text, llm_response, "reply"
        )
        _msg_type, message = pipeline.process_output(final_result)

        if message and message.strip():
            response = f"📚 **Learning Review**\n{message}"
        else:
            response = "Could not generate a review quiz. Try again?"

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

async def _handle_user_message(text: str, author: str) -> str:
    """Core handler: text in → response out. Used by both /learn and on_message."""
    _ensure_db()
    state.last_activity_at = datetime.now()

    # Full pipeline: context → kimi-cli (+ fetch loop) → execute
    llm_response = await pipeline.call_with_fetch_loop(
        "command", text, author
    )

    final_result = await pipeline.execute_llm_response(text, llm_response, "command")

    logger.debug(f"Agent result: {final_result[:500]!r}")

    msg_type, message = pipeline.process_output(final_result)
    logger.info(f"Completed: '{text[:50]}' → {msg_type}")
    return message


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
    logger.info("Commands: /learn /due /topics /review /clear /ping /sync (or !prefix)")
    logger.info("=" * 50)

    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync: {e}")

    # Start review scheduler
    scheduler.start(bot, config.AUTHORIZED_USER_ID)
    logger.info("[SCHEDULER] Review check started")

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

    # Route every plain message through the learning pipeline
    try:
        async with message.channel.typing():
            response = await _handle_user_message(text, str(message.author))

        if not response or not response.strip():
            response = "(empty response)"

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
