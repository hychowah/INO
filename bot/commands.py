"""Discord slash/hybrid command handlers."""

import asyncio
import functools
import logging

import config
import db
from bot.app import bot
from bot.auth import authorized_only
from bot.handler import (
    _ensure_db,
    _handle_user_message,
    _pending_confirmations,
)
from bot.messages import send_discord_result, send_long, send_long_with_view
from services import backup as backup_service
from services import chat_session, pipeline, state
from services.parser import parse_llm_response
from services.review_flow import generate_review_quiz_from_payload
from services.views import (
    AddConceptConfirmView,
    PreferenceUpdateView,
    SuggestTopicConfirmView,
)

logger = logging.getLogger("bot")


def _iter_action_buttons(action_block: dict) -> list[dict]:
    buttons = []
    for item in action_block.get("items", []):
        buttons.extend(item.get("buttons", []))
    buttons.extend(action_block.get("bulk_buttons", []))
    return buttons


def _proposal_view_from_action_block(action_block: dict):
    from services.views import DedupConfirmView, ProposedActionsView

    proposal_id = None
    source = "maintenance"
    for button in _iter_action_buttons(action_block):
        action = button.get("action", {})
        if proposal_id is None and action.get("proposal_id") is not None:
            proposal_id = int(action["proposal_id"])
        kind = str(action.get("kind", "")).lower().strip()
        if kind == "apply_dedup_groups":
            source = "dedup"
        elif kind in {"apply_maintenance_actions", "reject_proposals"}:
            source = str(action.get("source", source)).lower().strip() or source

    if proposal_id is None:
        raise ValueError("Proposal review block is missing proposal_id")

    proposal = db.get_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal #{proposal_id} is no longer available")

    payload = proposal.get("payload", [])
    if source == "dedup":
        return source, DedupConfirmView(proposal_id, payload)
    return source, ProposedActionsView(proposal_id, payload, source=source)


async def _send_discord_proposal_blocks(ctx, actions: list[dict] | None) -> None:
    if not actions:
        return

    is_interaction = ctx.interaction is not None
    for block in actions:
        if block.get("type") != "proposal_review":
            continue
        source, view = _proposal_view_from_action_block(block)
        title = block.get("title", f"{source.title()} proposals")
        description = block.get("description")
        content = f"⏳ **{title}**"
        if description:
            content += f"\n\n{description}"
        if is_interaction:
            await ctx.interaction.followup.send(content=content, view=view)
        else:
            await ctx.send(content=content, view=view)


def with_ctx_user_scope(func):
    @functools.wraps(func)
    async def wrapper(ctx, *args, **kwargs):
        with state.current_user_scope(state.get_local_user_id()):
            return await func(ctx, *args, **kwargs)

    return wrapper


@bot.hybrid_command(
    name="learn",
    description="AI learning coach — ask questions, get quizzed, track knowledge",
)
@authorized_only()
@with_ctx_user_scope
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
            active_user_id = state.get_local_user_id()
            response, pending_action, assess_meta, quiz_meta = await _handle_user_message(
                text or "hello", str(ctx.author), user_id=active_user_id
            )

        if pending_action:
            action_name = pending_action.get("action", "")
            if action_name == "suggest_topic":
                view = SuggestTopicConfirmView(pending_action)
            else:
                view = AddConceptConfirmView(pending_action)
            if is_interaction:
                send_fn = ctx.interaction.followup.send
            else:
                send_fn = ctx.send
            sent = await send_long_with_view(send_fn, response, view=view)
            _pending_confirmations[sent.id] = (pending_action, view)
            view.on_resolved = lambda mid=sent.id: _pending_confirmations.pop(mid, None)
        else:
            if is_interaction:
                send_fn = ctx.interaction.followup.send
            else:
                send_fn = ctx.send
            await send_discord_result(
                send_fn,
                response,
                _handle_user_message,
                assess_meta=assess_meta,
                quiz_meta=quiz_meta,
            )
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
@with_ctx_user_scope
async def sync_command(ctx):
    synced = await bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} command(s).")


@bot.hybrid_command(
    name="persona",
    description="View or switch persona preset (mentor/coach/buddy)",
)
@authorized_only()
@with_ctx_user_scope
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
        icons = {"mentor": "🎓", "coach": "🏋️", "buddy": "🤝"}
        descriptions = {
            "mentor": (
                "Calm, wise senior colleague — guides via questions, dry wit, measured enthusiasm"
            ),
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
        lines.append("\nSwitch with: `/persona <name>`")
        await send_long(ctx, "\n".join(lines))
        return

    target = name.strip().lower()
    if target == current:
        await ctx.send(f"Already using **{current.title()}** persona.")
        return

    try:
        async with state.pipeline_serialized():
            db.set_persona(target)
            pipeline.invalidate_prompt_cache()
            pipeline.reset_conversation_session()
    except ValueError:
        await ctx.send(f"Unknown persona `{target}`. Available: {', '.join(available)}")
        return

    icons = {"mentor": "🎓", "coach": "🏋️", "buddy": "🤝"}
    icon = icons.get(target, "🎭")
    await ctx.send(
        f"{icon} Switched to **{target.title()}** persona. Next message will use the new style."
    )


@bot.hybrid_command(name="due", description="Show concepts due for review")
@authorized_only()
@with_ctx_user_scope
async def due_command(ctx):
    """Show due concepts and review stats without calling the LLM."""
    _ensure_db()
    stats = db.get_review_stats()
    due = db.get_due_concepts(limit=10)

    lines = [
        f"📊 **{stats['due_now']}** due | **{stats['total_concepts']}** concepts | "
        f"avg score **{stats['avg_mastery']}/100** | "
        f"**{stats['reviews_last_7d']}** reviews this week\n"
    ]

    if due:
        lines.append("**Due for review:**")
        for c in due:
            remark = c.get("latest_remark", "")
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
@with_ctx_user_scope
async def topics_command(ctx):
    """Show the topic tree with mastery stats, no LLM call."""
    _ensure_db()
    from services.tools import _handle_list_topics

    msg_type, result = _handle_list_topics({})
    await send_long(ctx, result)


@bot.hybrid_command(name="clear", description="Clear chat history")
@authorized_only()
@with_ctx_user_scope
async def clear_command(ctx):
    """Clear learning agent chat history."""
    _ensure_db()
    async with state.pipeline_serialized():
        db.clear_chat_history()
    await ctx.send("🗑️ Chat history cleared.")


@bot.hybrid_command(
    name="maintain",
    description="Run maintenance + dedup check now",
)
@authorized_only()
@with_ctx_user_scope
async def maintain_command(ctx):
    """Manually trigger maintenance diagnostics and dedup agent."""
    if not config.MAINTENANCE_MODE_ENABLED:
        await send_long(
            ctx,
            "🔧 Maintenance mode is currently disabled. Use `/reorganize` for taxonomy work.",
        )
        return

    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    payload = await chat_session.handle_chat_message("/maintain", author=str(ctx.author), source="discord")
    await send_long(ctx, payload.get("message", ""))
    await _send_discord_proposal_blocks(ctx, payload.get("actions"))


@bot.hybrid_command(
    name="review",
    description="Pull your next due review quiz",
)
@authorized_only()
@with_ctx_user_scope
async def review_command(ctx):
    """Manually trigger a review quiz for the next due concept."""
    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)
    else:
        await ctx.typing()

    _ensure_db()

    review_lines = None
    discord_result = None
    try:
        async with state.pipeline_serialized():
            review_lines = pipeline.handle_review_check()
            if review_lines:
                async with ctx.channel.typing():
                    quiz = await generate_review_quiz_from_payload(
                        review_lines[0],
                        author=str(ctx.author),
                        source="discord",
                        track_in_progress=True,
                    )
                discord_result = quiz.to_discord_result()

        if not review_lines:
            msg = "✅ No concepts to review — add some topics first!"
            if is_interaction:
                await ctx.interaction.followup.send(msg)
            else:
                await ctx.send(msg)
            return

        response, _pending_action, assess_meta, quiz_meta = discord_result
        if is_interaction:
            send_fn = ctx.interaction.followup.send
        else:
            send_fn = ctx.send
        await send_discord_result(
            send_fn,
            response,
            _handle_user_message,
            assess_meta=assess_meta,
            quiz_meta=quiz_meta,
        )
    except Exception as e:
        logger.error(f"review_command error: {e}", exc_info=True)
        msg = f"Error: `{e}`"
        if is_interaction:
            await ctx.interaction.followup.send(msg)
        else:
            await ctx.send(msg)


@bot.hybrid_command(
    name="backup",
    description="Run a manual backup of all databases and vector store now",
)
@authorized_only()
@with_ctx_user_scope
async def backup_command(ctx):
    """Manually trigger a full backup-and-prune cycle."""
    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, backup_service.run_backup_cycle)

    if is_interaction:
        await ctx.interaction.followup.send(f"🗄️ {result}")
    else:
        await ctx.send(f"🗄️ {result}")


@bot.hybrid_command(
    name="reorganize",
    description="Run taxonomy reorganization — cluster and clean up the topic tree now",
)
@authorized_only()
@with_ctx_user_scope
async def reorganize_command(ctx):
    """Manually trigger the taxonomy reorganization agent."""
    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    try:
        payload = await chat_session.handle_chat_message(
            "/reorganize",
            author=str(ctx.author),
            source="discord",
        )
        await send_long(ctx, payload.get("message", ""))
        await _send_discord_proposal_blocks(ctx, payload.get("actions"))

    except Exception as e:
        logger.error(f"reorganize_command error: {e}", exc_info=True)
        err = f"🌿 **Taxonomy** — error: `{e}`"
        if is_interaction:
            await ctx.interaction.followup.send(err)
        else:
            await ctx.send(err)


@bot.hybrid_command(
    name="preference",
    description="View or update your preferences",
)
@authorized_only()
@with_ctx_user_scope
async def preference_command(ctx, *, text: str = ""):
    """Show current preferences (no args) or edit them via LLM (with args)."""
    is_interaction = ctx.interaction is not None

    _ensure_db()

    if not text:
        # Display mode — no LLM call needed
        try:
            content = config.PREFERENCES_MD.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = "_(preferences.md not found)_"
        await send_long(ctx, f"## Your Preferences\n\n```\n{content}\n```")
        return

    # Edit mode
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    try:
        async with state.pipeline_serialized():
            async with ctx.channel.typing():
                preview_text, proposed_content = await pipeline.call_preference_edit(text)

        view = PreferenceUpdateView(proposed_content, pipeline.execute_preference_update)
        msg = (
            "📝 **Proposed preference update**\n\n"
            f"{preview_text}\n\n"
            "*Review the change and confirm below.*"
        )
        if is_interaction:
            await ctx.interaction.followup.send(content=msg, view=view)
        else:
            await ctx.send(content=msg, view=view)

    except ValueError as e:
        err = f"⚠️ Could not parse LLM response: `{e}`"
        if is_interaction:
            await ctx.interaction.followup.send(err)
        else:
            await ctx.send(err)
    except Exception as e:
        logger.error(f"preference_command error: {e}", exc_info=True)
        err = f"⚠️ Preference update failed: `{e}`"
        if is_interaction:
            await ctx.interaction.followup.send(err)
        else:
            await ctx.send(err)
