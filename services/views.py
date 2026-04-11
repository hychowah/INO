"""
Discord UI views for confirmation flows (dedup, maintenance, concept addition).
Uses discord.py's Button/View components for safe, mobile-friendly interactions.

See DEVNOTES.md §4 for design rationale.
"""

import logging
from datetime import datetime
from typing import Awaitable, Callable

import discord

import db
from services import state
from services.dedup import execute_dedup_merges
from services.formatting import format_quiz_metadata, truncate_for_discord, truncate_with_suffix

logger = logging.getLogger("views")

# Timeout: 24 hours (matches proposal expiry)
VIEW_TIMEOUT = 86400


class DedupConfirmView(discord.ui.View):
    """View with per-group approve/reject buttons + bulk actions.

    Each dedup group gets a ✅/❌ button pair. The user can approve/reject
    individually, or use "Approve All" / "Reject All" for bulk action.

    State is stored in DB (pending_proposals) and survives bot restarts.
    The view is re-registered on bot startup via `register_persistent_views()`.
    """

    def __init__(self, proposal_id: int, groups: list[dict]):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposal_id = proposal_id
        self.groups = groups
        # Track per-group decisions: None=pending, True=approved, False=rejected
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(groups))}

        # Add bulk buttons first
        self.add_item(ApproveAllButton(self))
        self.add_item(RejectAllButton(self))

        # Add per-group buttons (Discord limit: 25 components / 5 rows)
        # Each group takes 2 components; with 2 bulk buttons, max ~11 groups
        max_groups = min(len(groups), 10)
        for i in range(max_groups):
            keep_concept = db.get_concept(groups[i]["keep"])
            label = keep_concept["title"][:30] if keep_concept else f"Group {i + 1}"
            self.add_item(ApproveGroupButton(self, i, label))
            self.add_item(RejectGroupButton(self, i, label))

    async def _finalize(self, interaction: discord.Interaction):
        """Check if all groups have decisions. If so, execute and clean up."""
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending:
            return  # Still waiting for more decisions

        # All decided — execute approved merges
        approved_groups = [self.groups[i] for i, d in self.decisions.items() if d]
        rejected_count = sum(1 for d in self.decisions.values() if not d)

        result_parts = []

        if approved_groups:
            summaries = await execute_dedup_merges(approved_groups)
            if summaries:
                result_parts.append(
                    f"✅ **Merged {len(summaries)} group(s):**\n"
                    + "\n".join(f"• {s}" for s in summaries)
                )

        if rejected_count:
            result_parts.append(f"❌ Rejected {rejected_count} group(s) — no changes made.")

        # Clean up proposal from DB
        db.delete_proposal(self.proposal_id)

        # Disable all buttons
        self._disable_all()

        # Edit the original message with results
        result_text = "\n\n".join(result_parts) if result_parts else "No merges executed."
        try:
            await interaction.message.edit(content=truncate_for_discord(result_text), view=self)
        except discord.errors.NotFound:
            pass

        self.stop()

    def _disable_all(self):
        """Disable all buttons (after completion or timeout)."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        """Called when the view times out (24h). Clean up proposal."""
        db.delete_proposal(self.proposal_id)
        self._disable_all()

    def _get_status_text(self) -> str:
        """Build a summary of current decisions for the message."""
        lines = []
        for i, g in enumerate(self.groups):
            keep_concept = db.get_concept(g["keep"])
            keep_title = keep_concept["title"] if keep_concept else f"#{g['keep']}"
            decision = self.decisions.get(i)
            if decision is True:
                status = "✅ Approved"
            elif decision is False:
                status = "❌ Rejected"
            else:
                status = "⏳ Pending"
            lines.append(f"**{i + 1}.** {keep_title} — {status}")
        return "\n".join(lines)


class ApproveAllButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView):
        super().__init__(
            label="Approve All",
            style=discord.ButtonStyle.success,
            emoji="✅",
            row=0,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for i in self.parent_view.decisions:
            self.parent_view.decisions[i] = True
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class RejectAllButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView):
        super().__init__(
            label="Reject All",
            style=discord.ButtonStyle.danger,
            emoji="❌",
            row=0,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for i in self.parent_view.decisions:
            self.parent_view.decisions[i] = False
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class ApproveGroupButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView, group_idx: int, label: str):
        # Row 1+ for per-group buttons (row 0 is bulk)
        row = min(4, (group_idx // 2) + 1)
        super().__init__(
            label=f"✅ {group_idx + 1}",
            style=discord.ButtonStyle.success,
            custom_id=f"dedup_approve_{group_idx}",
            row=row,
        )
        self.parent_view = parent_view
        self.group_idx = group_idx

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.decisions[self.group_idx] = True
        self.disabled = True
        # Also disable the corresponding reject button
        for item in self.parent_view.children:
            if isinstance(item, RejectGroupButton) and item.group_idx == self.group_idx:
                item.disabled = True
                break

        status = self.parent_view._get_status_text()
        await interaction.response.edit_message(
            content=truncate_for_discord(f"🔄 **Dedup Proposals**\n\n{status}"),
            view=self.parent_view,
        )
        await self.parent_view._finalize(interaction)


class RejectGroupButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView, group_idx: int, label: str):
        row = min(4, (group_idx // 2) + 1)
        super().__init__(
            label=f"❌ {group_idx + 1}",
            style=discord.ButtonStyle.danger,
            custom_id=f"dedup_reject_{group_idx}",
            row=row,
        )
        self.parent_view = parent_view
        self.group_idx = group_idx

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.decisions[self.group_idx] = False
        self.disabled = True
        # Also disable the corresponding approve button
        for item in self.parent_view.children:
            if isinstance(item, ApproveGroupButton) and item.group_idx == self.group_idx:
                item.disabled = True
                break

        status = self.parent_view._get_status_text()
        await interaction.response.edit_message(
            content=truncate_for_discord(f"🔄 **Dedup Proposals**\n\n{status}"),
            view=self.parent_view,
        )
        await self.parent_view._finalize(interaction)


# ============================================================================
# Proposed-actions confirmation view (maintenance, taxonomy, etc.)
# ============================================================================


class ProposedActionsView(discord.ui.View):
    """View for confirming proposed LLM actions (maintenance, taxonomy, etc.).
    Shows proposed actions with approve/reject buttons."""

    def __init__(
        self,
        proposal_id: int,
        actions: list[dict],
        execute_fn: Callable[[list[dict]], Awaitable[list[str]]],
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposal_id = proposal_id
        self.actions = actions
        self.execute_fn = execute_fn
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(actions))}
        self._finalizing: bool = False

        self.add_item(ApproveAllActionsButton(self))
        self.add_item(RejectAllActionsButton(self))

        max_actions = min(len(actions), 10)
        for i in range(max_actions):
            action_label = actions[i].get("action", "unknown")[:20]
            self.add_item(ApproveActionButton(self, i, action_label))
            self.add_item(RejectActionButton(self, i, action_label))

    async def _finalize(self, interaction: discord.Interaction):
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending:
            return
        if self._finalizing:
            return
        self._finalizing = True

        approved = [self.actions[i] for i, d in self.decisions.items() if d]
        rejected = [self.actions[i] for i, d in self.decisions.items() if d is False]

        result_parts = []
        async with state.pipeline_serialized():
            if approved:
                summaries = await self.execute_fn(approved)
                if summaries:
                    result_parts.append(
                        f"✅ **Executed {len(summaries)} action(s):**\n"
                        + "\n".join(f"• {s}" for s in summaries)
                    )

            # Log rejected rename actions BEFORE deleting proposal (prevents log loss on crash)
            for action in rejected:
                if action.get("action") in ("update_topic", "update_concept"):
                    db.log_action(
                        action=action["action"],
                        params=action.get("params", {}),
                        result_type="rejected",
                        result="",
                        source="maintenance",
                    )

            if rejected:
                result_parts.append(f"❌ Rejected {len(rejected)} action(s).")

            db.delete_proposal(self.proposal_id)
            self._disable_all()

        result_text = "\n\n".join(result_parts) if result_parts else "No actions executed."
        try:
            await interaction.message.edit(content=truncate_for_discord(result_text), view=self)
        except discord.errors.NotFound:
            pass
        self.stop()

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        db.delete_proposal(self.proposal_id)
        self._disable_all()


class ApproveAllActionsButton(discord.ui.Button):
    def __init__(self, parent_view: ProposedActionsView):
        super().__init__(label="Approve All", style=discord.ButtonStyle.success, emoji="✅", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for i in self.parent_view.decisions:
            self.parent_view.decisions[i] = True
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class RejectAllActionsButton(discord.ui.Button):
    def __init__(self, parent_view: ProposedActionsView):
        super().__init__(label="Reject All", style=discord.ButtonStyle.danger, emoji="❌", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for i in self.parent_view.decisions:
            self.parent_view.decisions[i] = False
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class ApproveActionButton(discord.ui.Button):
    def __init__(self, parent_view: ProposedActionsView, idx: int, label: str):
        row = min(4, (idx // 2) + 1)
        super().__init__(
            label=f"✅ {idx + 1}",
            style=discord.ButtonStyle.success,
            custom_id=f"maint_approve_{idx}",
            row=row,
        )
        self.parent_view = parent_view
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.decisions[self.idx] = True
        self.disabled = True
        for item in self.parent_view.children:
            if isinstance(item, RejectActionButton) and item.idx == self.idx:
                item.disabled = True
                break
        await interaction.response.edit_message(view=self.parent_view)
        await self.parent_view._finalize(interaction)


class RejectActionButton(discord.ui.Button):
    def __init__(self, parent_view: ProposedActionsView, idx: int, label: str):
        row = min(4, (idx // 2) + 1)
        super().__init__(
            label=f"❌ {idx + 1}",
            style=discord.ButtonStyle.danger,
            custom_id=f"maint_reject_{idx}",
            row=row,
        )
        self.parent_view = parent_view
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.decisions[self.idx] = False
        self.disabled = True
        for item in self.parent_view.children:
            if isinstance(item, ApproveActionButton) and item.idx == self.idx:
                item.disabled = True
                break
        await interaction.response.edit_message(view=self.parent_view)
        await self.parent_view._finalize(interaction)


# ============================================================================
# Add-concept confirmation view
# ============================================================================


class AddConceptConfirmView(discord.ui.View):
    """Simple Accept / Decline buttons shown when the LLM wants to add a
    concept during casual Q&A.  On Accept the concept is created via
    tools.execute_action; on Decline nothing happens.

    The *message* the user sees is the LLM's educational answer — the
    buttons are appended to that same message.
    """

    def __init__(self, action_data: dict, on_resolved: Callable | None = None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.action_data = action_data
        self.decided = False
        self.on_resolved = on_resolved

    @discord.ui.button(label="Add concept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        from services.tools import execute_action

        async with state.pipeline_serialized():
            action = self.action_data.get("action", "add_concept")
            params = self.action_data.get("params", {})
            msg_type, result = execute_action(action, params)

            if msg_type == "error":
                note = f"\n\n⚠️ Could not add concept: {result}"
            else:
                note = f"\n\n✅ {result}"
                # Persist confirmation to chat history so the LLM sees the
                # concept_id on subsequent turns (fixes topic_id/concept_id confusion)
                db.add_chat_message("user", "[confirmed: add concept]")
                db.add_chat_message("assistant", f"✅ {result}")

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(
                content=truncate_with_suffix(original, note), view=self
            )
        except discord.errors.NotFound:
            pass
        if self.on_resolved:
            self.on_resolved()
        self.stop()

    @discord.ui.button(label="No thanks", style=discord.ButtonStyle.secondary, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        async with state.pipeline_serialized():
            # Record decline so the LLM doesn't re-suggest the same concept
            db.add_chat_message("user", "[declined: add concept]")

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(
                content=truncate_for_discord(original), view=self
            )
        except discord.errors.NotFound:
            pass
        if self.on_resolved:
            self.on_resolved()
        self.stop()

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()
        if self.on_resolved:
            self.on_resolved()


# ============================================================================
# Suggest-topic confirmation view
# ============================================================================


class SuggestTopicConfirmView(discord.ui.View):
    """Accept / Decline buttons shown when the LLM uses suggest_topic for a
    new learning area.  On Accept the topic + initial concepts are created via
    tools.execute_suggest_topic_accept(); on Decline nothing happens.

    The *message* the user sees is the LLM's educational answer — the
    buttons are appended to that same message.
    """

    def __init__(self, action_data: dict, on_resolved: Callable | None = None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.action_data = action_data
        self.decided = False
        self.on_resolved = on_resolved

    @discord.ui.button(label="Add topic", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        from services.tools import execute_suggest_topic_accept

        async with state.pipeline_serialized():
            success, summary, topic_id = execute_suggest_topic_accept(self.action_data)

            title = self.action_data.get("params", {}).get("title", "topic")
            if success:
                db.add_chat_message("user", f'[confirmed: add topic "{title}"]')
                db.add_chat_message("assistant", summary)
                note = f"\n\n{summary}"
            else:
                note = f"\n\n⚠️ {summary}"

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(
                content=truncate_with_suffix(original, note), view=self
            )
        except discord.errors.NotFound:
            pass
        if self.on_resolved:
            self.on_resolved()
        self.stop()

    @discord.ui.button(label="No thanks", style=discord.ButtonStyle.secondary, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        async with state.pipeline_serialized():
            title = self.action_data.get("params", {}).get("title", "topic")
            db.add_chat_message("user", f'[declined: add topic "{title}"]')

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(
                content=truncate_for_discord(original), view=self
            )
        except discord.errors.NotFound:
            pass
        if self.on_resolved:
            self.on_resolved()
        self.stop()

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()
        if self.on_resolved:
            self.on_resolved()


# ============================================================================
# Quiz navigation view (post-assessment buttons)
# ============================================================================


class QuizNavigationView(discord.ui.View):
    """Buttons shown after a quiz assessment: continue, explain, or stop.

    Visual hierarchy swaps based on quality:
      - quality >= 3 (correct): "Next due" primary, "Quiz again" secondary
      - quality <= 2 (wrong):   "Explain" primary, "Quiz again" secondary

    The message_handler callable avoids a circular import with bot.py.
    It must have signature: async (str, str) -> tuple[str, dict|None, dict|None, dict|None]
    (response, pending_action, assess_meta, quiz_meta)
    """

    def __init__(self, concept_id: int, quality: int, message_handler: Callable[..., Awaitable]):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.concept_id = concept_id
        self.quality = quality
        self.message_handler = message_handler
        self.clicked = False

        if quality >= 3:
            # Correct: emphasize "Next due", secondary "Quiz again"
            self.add_item(_QuizNextDueButton(self, style=discord.ButtonStyle.primary))
            self.add_item(_QuizAgainButton(self, style=discord.ButtonStyle.secondary))
        else:
            # Wrong: emphasize "Explain", secondary "Quiz again", then "Next due"
            self.add_item(_QuizExplainButton(self, style=discord.ButtonStyle.primary))
            self.add_item(_QuizAgainButton(self, style=discord.ButtonStyle.secondary))
            self.add_item(_QuizNextDueButton(self, style=discord.ButtonStyle.secondary))

        # "Done" always present, always secondary
        self.add_item(_QuizDoneButton(self))

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()


class _QuizAgainButton(discord.ui.Button):
    """Quiz the same concept again."""

    def __init__(
        self,
        parent_view: QuizNavigationView,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ):
        super().__init__(label="Quiz again", emoji="🔄", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        concept = db.get_concept(self.parent_view.concept_id)
        title = concept["title"] if concept else f"#{self.parent_view.concept_id}"
        text = f"[BUTTON] Quiz me again on concept #{self.parent_view.concept_id} ({title})"

        try:
            async with interaction.channel.typing():
                response, _, _, quiz_meta = await self.parent_view.message_handler(
                    text, str(interaction.user)
                )
            await _send_quiz_response(
                interaction,
                response,
                self.parent_view.message_handler,
                quiz_meta=quiz_meta,
            )
        except Exception as e:
            logger.error(f"QuizAgain callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


class _QuizNextDueButton(discord.ui.Button):
    """Quiz the next concept that's due for review."""

    def __init__(
        self,
        parent_view: QuizNavigationView,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ):
        super().__init__(label="Next due", emoji="⏭️", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        if db.get_session("pending_review"):
            await interaction.followup.send(
                "⏳ A scheduled review was just sent — reply to that one first."
            )
            self.parent_view.stop()
            return

        text = "[BUTTON] Quiz me on the next due concept"
        try:
            async with interaction.channel.typing():
                response, _, _, quiz_meta = await self.parent_view.message_handler(
                    text, str(interaction.user)
                )
            await _send_quiz_response(
                interaction,
                response,
                self.parent_view.message_handler,
                quiz_meta=quiz_meta,
            )
        except Exception as e:
            logger.error(f"QuizNextDue callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


class _QuizExplainButton(discord.ui.Button):
    """Explain the concept (shown only when quality <= 2)."""

    def __init__(
        self,
        parent_view: QuizNavigationView,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ):
        super().__init__(label="Explain", emoji="💡", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        concept = db.get_concept(self.parent_view.concept_id)
        title = concept["title"] if concept else f"#{self.parent_view.concept_id}"
        text = (
            f"[BUTTON] Explain concept #{self.parent_view.concept_id} ({title}) "
            f"in detail — I got the quiz wrong and need help understanding it"
        )

        try:
            async with interaction.channel.typing():
                response, _, _, _ = await self.parent_view.message_handler(
                    text, str(interaction.user)
                )
            # Explain is not an assess, so send plain (no nav buttons)
            await interaction.followup.send(
                truncate_for_discord(response or "(no explanation generated)")
            )
        except Exception as e:
            logger.error(f"QuizExplain callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


class _QuizDoneButton(discord.ui.Button):
    """End the quiz session."""

    def __init__(self, parent_view: QuizNavigationView):
        super().__init__(label="Done", emoji="✋", style=discord.ButtonStyle.secondary, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        original = interaction.message.content or ""
        try:
            await interaction.response.edit_message(
                content=truncate_with_suffix(original, "\n\n✋ Quiz session ended."),
                view=self.parent_view,
            )
        except discord.errors.NotFound:
            pass
        self.parent_view.stop()


# ============================================================================
# Quiz question view (pre-answer skip button)
# ============================================================================


class QuizQuestionView(discord.ui.View):
    """Optional button shown with quiz questions: allows skipping if eligible.

    Only contains the skip button when show_skip=True (concept has
    review_count >= 2). The message_handler is passed through to
    QuizNavigationView for post-skip navigation.
    """

    def __init__(
        self, concept_id: int, message_handler: Callable[..., Awaitable], show_skip: bool = True
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.concept_id = concept_id
        self.message_handler = message_handler
        self.clicked = False

        if show_skip:
            self.add_item(_QuizSkipButton(self))

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()


def should_show_quiz_skip_button(concept: dict | None) -> bool:
    """Return whether a concept is eligible for the quiz skip button."""
    return bool(concept and concept.get("review_count", 0) >= 2)


class _QuizSkipButton(discord.ui.Button):
    """Skip the quiz — user claims confident recall."""

    def __init__(self, parent_view: QuizQuestionView):
        super().__init__(label="I know this", emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        from services.tools_assess import skip_quiz

        try:
            async with state.pipeline_serialized():
                result = skip_quiz(
                    self.parent_view.concept_id,
                    user_id=str(interaction.user),
                )

                if "error" in result:
                    await interaction.followup.send(f"⚠️ {result['error']}")
                    self.parent_view.stop()
                    return

                state.last_activity_at = datetime.now()
                confirmation = (
                    f"⏭️ Skipped — score: {result['old_score']}→{result['new_score']}, "
                    f"next review in {result['interval_days']}d"
                )
                nav_view = QuizNavigationView(
                    concept_id=result["concept_id"],
                    quality=5,
                    message_handler=self.parent_view.message_handler,
                )
            await interaction.followup.send(confirmation, view=nav_view)
        except Exception as e:
            logger.error(f"QuizSkip callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


async def _send_quiz_response(
    interaction: discord.Interaction,
    response: str,
    message_handler: Callable[..., Awaitable],
    *,
    quiz_meta: dict | None = None,
) -> None:
    """Send the LLM response from a quiz button click.

    Prefer explicit quiz metadata from the handler. Fall back to session state
    only for callers that do not provide quiz_meta.
    """
    if not response or not response.strip():
        response = "✅ No concepts due right now!"

    if quiz_meta is not None:
        quiz_cid = quiz_meta.get("concept_id")
        if quiz_cid is not None and quiz_meta.get("show_skip"):
            concept = db.get_concept(int(quiz_cid))
            if should_show_quiz_skip_button(concept):
                meta = format_quiz_metadata(concept)
                meta_suffix = f"\n\n{meta}" if meta else ""
                view = QuizQuestionView(
                    concept_id=int(quiz_cid),
                    message_handler=message_handler,
                    show_skip=True,
                )
                await interaction.followup.send(
                    truncate_for_discord(response + meta_suffix), view=view
                )
                return
            # show_skip=True but not yet eligible — reuse already-fetched concept
            meta = format_quiz_metadata(concept)
            meta_suffix = f"\n\n{meta}" if meta else ""
            await interaction.followup.send(truncate_for_discord(response + meta_suffix))
            return

        # show_skip=False: fetch concept for metadata only
        if quiz_cid is not None:
            concept = db.get_concept(int(quiz_cid))
            meta = format_quiz_metadata(concept)
            meta_suffix = f"\n\n{meta}" if meta else ""
        else:
            meta_suffix = ""
        await interaction.followup.send(truncate_for_discord(response + meta_suffix))
        return

    quiz_cid = db.get_session("quiz_anchor_concept_id")
    if quiz_cid:
        concept = db.get_concept(int(quiz_cid))
        if should_show_quiz_skip_button(concept):
            meta = format_quiz_metadata(concept)
            meta_suffix = f"\n\n{meta}" if meta else ""
            view = QuizQuestionView(
                concept_id=int(quiz_cid),
                message_handler=message_handler,
                show_skip=True,
            )
            await interaction.followup.send(truncate_for_discord(response + meta_suffix), view=view)
            return
        # session anchor exists but skip not eligible yet — still add metadata
        meta = format_quiz_metadata(concept)
        meta_suffix = f"\n\n{meta}" if meta else ""
        await interaction.followup.send(truncate_for_discord(response + meta_suffix))
        return

    await interaction.followup.send(truncate_for_discord(response))


# ============================================================================
# Preference update confirmation view
# ============================================================================


class PreferenceUpdateView(discord.ui.View):
    """Apply / Reject buttons shown when the user proposes a preference edit.

    Proposed content is held in-memory (self.proposed_content); no DB proposal
    needed for a single-file write operation.
    """

    def __init__(self, proposed_content: str, execute_callback: Callable[..., Awaitable[str]]):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposed_content = proposed_content
        self.execute_callback = execute_callback
        self.decided = False

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.success, emoji="✅")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()
        try:
            result = await self.execute_callback(self.proposed_content)
        except Exception as e:
            logger.error(f"PreferenceUpdateView apply error: {e}", exc_info=True)
            result = f"⚠️ Failed to update preferences: {e}"
        try:
            await interaction.response.edit_message(content=result, view=self)
        except discord.errors.NotFound:
            pass
        self.stop()

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()
        try:
            await interaction.response.edit_message(content="Update discarded.", view=self)
        except discord.errors.NotFound:
            pass
        self.stop()

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()
