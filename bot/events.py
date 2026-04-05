"""Discord event handlers — on_ready, on_message, on_command_error."""

import asyncio
import logging

import discord
from discord.ext import commands

import config
import db
from services import pipeline, scheduler
from services.views import AddConceptConfirmView, QuizNavigationView, QuizQuestionView, SuggestTopicConfirmView
from services.formatting import truncate_with_suffix, format_quiz_metadata

from bot.app import bot
from bot.messages import send_long, send_long_with_view
from bot.handler import (
    _handle_user_message,
    _pending_confirmations,
    _ensure_db,
    _is_affirmative,
    _is_negative,
)

logger = logging.getLogger("bot")


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

    scheduler.start(bot, config.AUTHORIZED_USER_ID)
    logger.info("[SCHEDULER] Review check started")

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

    if message.reference and message.reference.message_id in _pending_confirmations:
        action_data, view = _pending_confirmations[message.reference.message_id]
        if not view.decided:
            reply_text = text.lower().strip()
            action_name = action_data.get('action', '').lower().strip()
            if _is_affirmative(reply_text):
                view.decided = True
                view._disable_all()
                if action_name == 'suggest_topic':
                    from services.tools import execute_suggest_topic_accept
                    success, summary, topic_id = execute_suggest_topic_accept(action_data)
                    title = action_data.get('params', {}).get('title', 'topic')
                    if success:
                        db.add_chat_message('user', f'[confirmed: add topic "{title}"]')
                        db.add_chat_message('assistant', summary)
                        note = f"\n\n{summary}"
                    else:
                        note = f"\n\n⚠️ {summary}"
                else:
                    from services.tools import execute_action
                    msg_type, result = execute_action(
                        action_data.get('action', 'add_concept'),
                        action_data.get('params', {}),
                    )
                    note = f"\n\n⚠️ Could not add concept: {result}" if msg_type == 'error' \
                        else f"\n\n✅ {result}"
                    if msg_type != 'error':
                        db.add_chat_message('user', '[confirmed: add concept]')
                        db.add_chat_message('assistant', f"✅ {result}")
                try:
                    orig = await message.channel.fetch_message(message.reference.message_id)
                    await orig.edit(
                        content=truncate_with_suffix(orig.content or '', note),
                        view=view)
                except discord.errors.NotFound:
                    pass
                _pending_confirmations.pop(message.reference.message_id, None)
                await message.add_reaction('✅')
                return
            elif _is_negative(reply_text):
                view.decided = True
                view._disable_all()
                if action_name == 'suggest_topic':
                    title = action_data.get('params', {}).get('title', 'topic')
                    db.add_chat_message('user', f'[declined: add topic "{title}"]')
                else:
                    db.add_chat_message('user', '[declined: add concept]')
                try:
                    orig = await message.channel.fetch_message(message.reference.message_id)
                    await orig.edit(view=view)
                except discord.errors.NotFound:
                    pass
                _pending_confirmations.pop(message.reference.message_id, None)
                await message.add_reaction('👍')
                return

    try:
        async with message.channel.typing():
            response, pending_action, assess_meta, quiz_meta = await _handle_user_message(
                text, str(message.author))

        if not response or not response.strip():
            response = "(empty response)"

        if pending_action:
            action_name = pending_action.get('action', '')
            if action_name == 'suggest_topic':
                view = SuggestTopicConfirmView(pending_action)
            else:
                view = AddConceptConfirmView(pending_action)
            sent = await send_long_with_view(message.reply, response, view=view)
            _pending_confirmations[sent.id] = (pending_action, view)
            view.on_resolved = lambda mid=sent.id: _pending_confirmations.pop(mid, None)
        elif assess_meta:
            view = QuizNavigationView(
                concept_id=assess_meta['concept_id'],
                quality=assess_meta['quality'],
                message_handler=_handle_user_message,
            )
            await send_long_with_view(message.reply, response, view=view)
        elif quiz_meta:
            concept = db.get_concept(quiz_meta['concept_id'])
            meta = format_quiz_metadata(concept)
            meta_suffix = f"\n\n{meta}" if meta else ""
            view = None
            if quiz_meta.get('show_skip'):
                view = QuizQuestionView(
                    concept_id=quiz_meta['concept_id'],
                    message_handler=_handle_user_message,
                    show_skip=True,
                )
            await send_long_with_view(message.reply, response + meta_suffix, view=view)
        else:
            await send_long_with_view(message.reply, response)

    except Exception as e:
        logger.error(f"Message handler error: {e}", exc_info=True)
        await message.reply(f"Error: `{e}`")
