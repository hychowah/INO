"""Discord event handlers — on_ready, on_message, on_command_error."""

import asyncio
import logging
import shutil

import discord
from discord.ext import commands

import config
import db
from bot.app import bot
from bot.handler import (
    _handle_user_message,
    _is_affirmative,
    _is_negative,
    _pending_confirmations,
)
from bot.messages import send_discord_result, send_long_with_view
from services import pipeline, scheduler, state
from services.chat_actions import execute_lightweight_confirm, execute_lightweight_decline
from services.formatting import truncate_with_suffix
from services.views import (
    AddConceptConfirmView,
    SuggestTopicConfirmView,
)

logger = logging.getLogger("bot")


@bot.event
async def on_ready():
    pipeline.init_databases()

    if not config.PREFERENCES_MD.exists() and config.PREFERENCES_TEMPLATE_MD.exists():
        shutil.copy(config.PREFERENCES_TEMPLATE_MD, config.PREFERENCES_MD)
        logger.info("Copied preferences.template.md → preferences.md")
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

    scheduler.start(bot, config.AUTHORIZED_USER_ID, owner_label="bot")
    logger.info("[SCHEDULER] Review and shared background loops started")

    bot.loop.create_task(_heartbeat())


async def _heartbeat():
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(300)
        latency_ms = round(bot.latency * 1000)
        logger.info(f"[HEARTBEAT] alive | latency={latency_ms}ms")


@bot.event
async def on_disconnect():
    scheduler.stop()
    logger.info("[SCHEDULER] Background loops stopped")


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

    if message.content.startswith(("!", "/")):
        await bot.process_commands(message)
        return

    text = message.content.strip()
    if not text:
        await bot.process_commands(message)
        return

    with state.current_user_scope(state.get_local_user_id()):
        if message.reference and message.reference.message_id in _pending_confirmations:
            action_data, view = _pending_confirmations[message.reference.message_id]
            if not view.decided:
                reply_text = text.lower().strip()
                if _is_affirmative(reply_text):
                    view.decided = True
                    view._disable_all()
                    async with state.pipeline_serialized():
                        _success, display_note = execute_lightweight_confirm(
                            action_data,
                            source="discord",
                        )
                        note = f"\n\n{display_note}"
                    try:
                        orig = await message.channel.fetch_message(message.reference.message_id)
                        await orig.edit(
                            content=truncate_with_suffix(orig.content or "", note), view=view
                        )
                    except discord.errors.NotFound:
                        pass
                    _pending_confirmations.pop(message.reference.message_id, None)
                    await message.add_reaction("✅")
                    return
                elif _is_negative(reply_text):
                    view.decided = True
                    view._disable_all()
                    async with state.pipeline_serialized():
                        execute_lightweight_decline(action_data)
                    try:
                        orig = await message.channel.fetch_message(message.reference.message_id)
                        await orig.edit(view=view)
                    except discord.errors.NotFound:
                        pass
                    _pending_confirmations.pop(message.reference.message_id, None)
                    await message.add_reaction("👍")
                    return

        try:
            async with message.channel.typing():
                active_user_id = state.get_local_user_id()
                response, pending_action, assess_meta, quiz_meta = await _handle_user_message(
                    text, str(message.author), user_id=active_user_id
                )

            if not response or not response.strip():
                response = "(empty response)"

            if pending_action:
                action_name = pending_action.get("action", "")
                if action_name == "suggest_topic":
                    view = SuggestTopicConfirmView(pending_action)
                else:
                    view = AddConceptConfirmView(pending_action)
                sent = await send_long_with_view(message.reply, response, view=view)
                _pending_confirmations[sent.id] = (pending_action, view)
                view.on_resolved = lambda mid=sent.id: _pending_confirmations.pop(mid, None)
            else:
                await send_discord_result(
                    message.reply,
                    response,
                    _handle_user_message,
                    assess_meta=assess_meta,
                    quiz_meta=quiz_meta,
                )

        except Exception as e:
            logger.error(f"Message handler error: {e}", exc_info=True)
            await message.reply(f"Error: `{e}`")
