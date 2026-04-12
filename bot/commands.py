"""Discord slash/hybrid command handlers."""

import asyncio
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
from bot.messages import send_long, send_long_with_view, send_review_question
from services import backup as backup_service
from services import pipeline, state
from services.formatting import format_quiz_metadata
from services.parser import parse_llm_response
from services.views import (
    AddConceptConfirmView,
    PreferenceUpdateView,
    QuizNavigationView,
    QuizQuestionView,
    SuggestTopicConfirmView,
)

logger = logging.getLogger("bot")


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
            response, pending_action, assess_meta, quiz_meta = await _handle_user_message(
                text or "hello", str(ctx.author)
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
        elif assess_meta:
            view = QuizNavigationView(
                concept_id=assess_meta["concept_id"],
                quality=assess_meta["quality"],
                message_handler=_handle_user_message,
            )
            if is_interaction:
                send_fn = ctx.interaction.followup.send
            else:
                send_fn = ctx.send
            await send_long_with_view(send_fn, response, view=view)
        elif quiz_meta:
            concept = db.get_concept(quiz_meta["concept_id"])
            meta = format_quiz_metadata(concept)
            meta_suffix = f"\n\n{meta}" if meta else ""
            view = None
            if quiz_meta.get("show_skip"):
                view = QuizQuestionView(
                    concept_id=quiz_meta["concept_id"],
                    message_handler=_handle_user_message,
                    show_skip=True,
                )
            if is_interaction:
                send_fn = ctx.interaction.followup.send
            else:
                send_fn = ctx.send
            await send_long_with_view(send_fn, response + meta_suffix, view=view)
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
    async with state.pipeline_serialized():
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
    from services.views import DedupConfirmView, ProposedActionsView

    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    _ensure_db()
    parts = []

    proposed_actions = []
    groups = None
    async with state.pipeline_serialized():
        try:
            maint_context = pipeline.handle_maintenance()
            if maint_context:
                async with ctx.channel.typing():
                    result, proposed_actions = await pipeline.call_maintenance_loop(maint_context)
                    msg = result
                    for pfx in ("REPLY: ", "REPLY:"):
                        if msg.startswith(pfx):
                            msg = msg[len(pfx) :]
                    if msg.strip():
                        parts.append(f"🔧 **Maintenance**\n{msg.strip()}")
            else:
                parts.append("🔧 **Maintenance** — no issues found ✅")
        except Exception as e:
            logger.error(f"maintain_command maint error: {e}", exc_info=True)
            parts.append(f"🔧 **Maintenance** — error: `{e}`")

        try:
            existing = db.get_pending_proposal("dedup")
            if existing:
                parts.append("🔄 **Dedup** — pending proposal already exists, check your DMs")
            else:
                async with ctx.channel.typing():
                    groups = await pipeline.handle_dedup_check()
                if groups:
                    proposal_id = db.save_proposal("dedup", groups)
                    suggestion_text = format_dedup_suggestions(groups)
                    view = DedupConfirmView(proposal_id, groups)
                    parts.append(suggestion_text)
                else:
                    parts.append("🔄 **Dedup** — no duplicates found ✅")
        except Exception as e:
            logger.error(f"maintain_command dedup error: {e}", exc_info=True)
            parts.append(f"🔄 **Dedup** — error: `{e}`")
            groups = None

    main_text = "\n\n".join(parts)

    views_to_send = []
    if groups:
        views_to_send.append(("dedup", view))
    if proposed_actions:
        maint_proposal_id = db.save_proposal("maintenance", proposed_actions)
        maint_view = ProposedActionsView(
            maint_proposal_id,
            proposed_actions,
            pipeline.execute_maintenance_actions,
        )
        views_to_send.append(("maintenance", maint_view))

    if views_to_send:
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

    review_lines = None
    cid = None
    response = None
    assess_meta = None
    try:
        async with state.pipeline_serialized():
            review_lines = pipeline.handle_review_check()
            if review_lines:
                payload = review_lines[0]
                review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"

                try:
                    cid = int(payload.split("|", 1)[0])
                except (ValueError, IndexError):
                    cid = None

                try:
                    if cid:
                        db.set_session("active_concept_id", str(cid))
                        db.set_session("quiz_anchor_concept_id", str(cid))

                    db.set_session("review_in_progress", str(cid) if cid else "1")

                    async with ctx.channel.typing():
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
                                f"Two-prompt pipeline failed ({e}), falling back to single-prompt flow"
                            )
                            llm_response = await pipeline.call_with_fetch_loop(
                                mode="reply",
                                text=review_text,
                                author=str(ctx.author),
                            )

                        final_result = await pipeline.execute_llm_response(
                            review_text, llm_response, "reply"
                        )
                        _msg_type, response = pipeline.process_output(final_result)
                        assess_meta = None

                        if _msg_type == "reply":
                            prefix, _msg, action_data = parse_llm_response(llm_response)
                            if (
                                action_data
                                and action_data.get("action", "").lower().strip() == "assess"
                                and action_data.get("params", {}).get("quality") is not None
                            ):
                                assess_meta = {
                                    "concept_id": action_data["params"].get("concept_id", cid),
                                    "quality": action_data["params"]["quality"],
                                }

                    if not response or not response.strip():
                        response = "Could not generate a review quiz. Try again?"
                    else:
                        db.set_session("last_quiz_question", response.strip())
                finally:
                    db.set_session("review_in_progress", None)

        if not review_lines:
            msg = "✅ No concepts to review — add some topics first!"
            if is_interaction:
                await ctx.interaction.followup.send(msg)
            else:
                await ctx.send(msg)
            return

        if assess_meta:
            response = f"📚 **Learning Review**\n{response}"
            view = QuizNavigationView(
                concept_id=assess_meta["concept_id"],
                quality=assess_meta["quality"],
                message_handler=_handle_user_message,
            )
            if is_interaction:
                send_fn = ctx.interaction.followup.send
            else:
                send_fn = ctx.send
            await send_long_with_view(send_fn, response, view=view)
        elif cid:
            if is_interaction:
                send_fn = ctx.interaction.followup.send
            else:
                send_fn = ctx.send
            await send_review_question(send_fn, response, cid, _handle_user_message)
        else:
            await send_long(ctx, response)
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
async def reorganize_command(ctx):
    """Manually trigger the taxonomy reorganization agent."""
    from services.views import ProposedActionsView

    is_interaction = ctx.interaction is not None
    if is_interaction:
        await ctx.interaction.response.defer(ephemeral=False)

    _ensure_db()

    try:
        async with state.pipeline_serialized():
            async with ctx.channel.typing():
                taxonomy_context = pipeline.handle_taxonomy()
                if not taxonomy_context:
                    msg = "🌿 **Taxonomy** — no topics found yet ✅"
                    if is_interaction:
                        await ctx.interaction.followup.send(msg)
                    else:
                        await ctx.send(msg)
                    return

                final_result, proposed_actions = await pipeline.call_taxonomy_loop(taxonomy_context)

        msg = final_result
        for pfx in ("REPLY: ", "REPLY:"):
            if msg.startswith(pfx):
                msg = msg[len(pfx) :]
        main_text = (
            f"🌿 **Taxonomy Reorganization**\n\n{msg.strip()}"
            if msg.strip()
            else "🌿 **Taxonomy Reorganization** — complete ✅"
        )

        if proposed_actions:
            proposal_id = db.save_proposal("taxonomy", proposed_actions)
            view = ProposedActionsView(
                proposal_id,
                proposed_actions,
                pipeline.execute_maintenance_actions,
            )
            await send_long(ctx, main_text)
            approve_text = "⏳ **Proposed taxonomy changes — approve or reject:**"
            if is_interaction:
                await ctx.interaction.followup.send(content=approve_text, view=view)
            else:
                await ctx.send(content=approve_text, view=view)
        else:
            await send_long(ctx, main_text)

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
        msg = f"📝 **Proposed preference update**\n\n{preview_text}\n\n*Review the change and confirm below.*"
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
