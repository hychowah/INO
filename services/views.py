"""Discord UI views for confirmation flows and quiz actions."""

import logging
from datetime import datetime
from typing import Awaitable, Callable

import discord

import db
from services import state
from services.chat_actions import resolve_lightweight_confirmation
from services.chat_quiz import build_quiz_followup_prompt, execute_skip_quiz_action
from services.chat_session import confirm_chat_action, decline_chat_action, handle_chat_action
from services.formatting import format_quiz_metadata, truncate_for_discord, truncate_with_suffix
from services.review_state import get_pending_review, register_interactive_review_delivery

logger = logging.getLogger("views")

VIEW_TIMEOUT = 86400


def _interaction_user_id(interaction: discord.Interaction) -> str:
    return state.get_local_user_id()


class DedupConfirmView(discord.ui.View):
    """View with per-group approve/reject buttons plus bulk actions."""

    def __init__(self, proposal_id: int, groups: list[dict]):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposal_id = proposal_id
        self.groups = groups
        self.proposal_user_id = state.get_current_user()
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(groups))}

        self.add_item(ApproveAllButton(self))
        self.add_item(RejectAllButton(self))

        max_groups = min(len(groups), 10)
        for i in range(max_groups):
            keep_concept = db.get_concept(groups[i]["keep"])
            label = keep_concept["title"][:30] if keep_concept else f"Group {i + 1}"
            self.add_item(ApproveGroupButton(self, i, label))
            self.add_item(RejectGroupButton(self, i, label))

    async def _finalize(self, interaction: discord.Interaction):
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending:
            return

        approved_ids = [f"dedup-{i}" for i, decision in self.decisions.items() if decision is True]
        rejected_ids = [f"dedup-{i}" for i, decision in self.decisions.items() if decision is False]
        result_parts = []

        with state.current_user_scope(self.proposal_user_id):
            if approved_ids:
                payload = await handle_chat_action(
                    {
                        "kind": "apply_dedup_groups",
                        "proposal_id": self.proposal_id,
                        "proposal_item_ids": approved_ids,
                    },
                    source="discord",
                )
                if payload.get("message"):
                    result_parts.append(payload["message"])
            if rejected_ids:
                payload = await handle_chat_action(
                    {
                        "kind": "reject_proposals",
                        "proposal_id": self.proposal_id,
                        "proposal_item_ids": rejected_ids,
                        "source": "dedup",
                    },
                    source="discord",
                )
                if payload.get("message"):
                    result_parts.append(payload["message"])

        self._disable_all()
        result_text = "\n\n".join(result_parts) if result_parts else "No merges executed."
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
        with state.current_user_scope(self.proposal_user_id):
            db.delete_proposal(self.proposal_id, user_id=self.proposal_user_id)
        self._disable_all()

    def _get_status_text(self) -> str:
        lines = []
        for index, group in enumerate(self.groups):
            keep_concept = db.get_concept(group["keep"])
            keep_title = keep_concept["title"] if keep_concept else f"#{group['keep']}"
            decision = self.decisions.get(index)
            if decision is True:
                status = "✅ Approved"
            elif decision is False:
                status = "❌ Rejected"
            else:
                status = "⏳ Pending"
            lines.append(f"**{index + 1}.** {keep_title} — {status}")
        return "\n".join(lines)


class ApproveAllButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView):
        super().__init__(label="Approve All", style=discord.ButtonStyle.success, emoji="✅", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for index in self.parent_view.decisions:
            self.parent_view.decisions[index] = True
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class RejectAllButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView):
        super().__init__(label="Reject All", style=discord.ButtonStyle.danger, emoji="❌", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for index in self.parent_view.decisions:
            self.parent_view.decisions[index] = False
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class ApproveGroupButton(discord.ui.Button):
    def __init__(self, parent_view: DedupConfirmView, group_idx: int, label: str):
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


class ProposedActionsView(discord.ui.View):
    """View for confirming proposed LLM actions."""

    def __init__(
        self,
        proposal_id: int,
        actions: list[dict],
        *,
        source: str = "maintenance",
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposal_id = proposal_id
        self.actions = actions
        self.source = source
        self.proposal_user_id = state.get_current_user()
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(actions))}
        self._finalizing = False

        self.add_item(ApproveAllActionsButton(self))
        self.add_item(RejectAllActionsButton(self))

        max_actions = min(len(actions), 10)
        for index in range(max_actions):
            action_label = actions[index].get("action", "unknown")[:20]
            self.add_item(ApproveActionButton(self, index, action_label))
            self.add_item(RejectActionButton(self, index, action_label))

    async def _finalize(self, interaction: discord.Interaction):
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending or self._finalizing:
            return
        self._finalizing = True

        approved_ids = [f"{self.source}-{i}" for i, decision in self.decisions.items() if decision is True]
        rejected_ids = [f"{self.source}-{i}" for i, decision in self.decisions.items() if decision is False]
        result_parts = []

        with state.current_user_scope(self.proposal_user_id):
            if approved_ids:
                payload = await handle_chat_action(
                    {
                        "kind": "apply_maintenance_actions",
                        "proposal_id": self.proposal_id,
                        "proposal_item_ids": approved_ids,
                        "source": self.source,
                    },
                    source="discord",
                )
                if payload.get("message"):
                    result_parts.append(payload["message"])
            if rejected_ids:
                payload = await handle_chat_action(
                    {
                        "kind": "reject_proposals",
                        "proposal_id": self.proposal_id,
                        "proposal_item_ids": rejected_ids,
                        "source": self.source,
                    },
                    source="discord",
                )
                if payload.get("message"):
                    result_parts.append(payload["message"])
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
        with state.current_user_scope(self.proposal_user_id):
            db.delete_proposal(self.proposal_id, user_id=self.proposal_user_id)
        self._disable_all()


class ApproveAllActionsButton(discord.ui.Button):
    def __init__(self, parent_view: ProposedActionsView):
        super().__init__(label="Approve All", style=discord.ButtonStyle.success, emoji="✅", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for index in self.parent_view.decisions:
            self.parent_view.decisions[index] = True
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class RejectAllActionsButton(discord.ui.Button):
    def __init__(self, parent_view: ProposedActionsView):
        super().__init__(label="Reject All", style=discord.ButtonStyle.danger, emoji="❌", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for index in self.parent_view.decisions:
            self.parent_view.decisions[index] = False
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


class _LightweightConfirmView(discord.ui.View):
    def __init__(self, action_data: dict, on_resolved: Callable | None = None):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.action_data = action_data
        self.decided = False
        self.on_resolved = on_resolved

    async def _accept_action(self, interaction: discord.Interaction):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        display_note = await resolve_lightweight_confirmation(
            self.action_data,
            approve=True,
            user_id=_interaction_user_id(interaction),
        )
        note = f"\n\n{display_note}"

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(
                content=truncate_with_suffix(original, note), view=self
            )
        except discord.errors.NotFound:
            pass
        self._finish_resolution()

    async def _decline_action(self, interaction: discord.Interaction):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        await resolve_lightweight_confirmation(
            self.action_data,
            approve=False,
            user_id=_interaction_user_id(interaction),
        )

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(
                content=truncate_for_discord(original), view=self
            )
        except discord.errors.NotFound:
            pass
        self._finish_resolution()

    def _finish_resolution(self):
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


class AddConceptConfirmView(_LightweightConfirmView):
    """Accept or decline adding a concept."""

    def __init__(self, action_data: dict, on_resolved: Callable | None = None):
        super().__init__(action_data, on_resolved=on_resolved)

    @discord.ui.button(label="Add concept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._accept_action(interaction)

    @discord.ui.button(label="No thanks", style=discord.ButtonStyle.secondary, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decline_action(interaction)


class SuggestTopicConfirmView(_LightweightConfirmView):
    """Accept or decline adding a suggested topic."""

    def __init__(self, action_data: dict, on_resolved: Callable | None = None):
        super().__init__(action_data, on_resolved=on_resolved)

    @discord.ui.button(label="Add topic", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._accept_action(interaction)

    @discord.ui.button(label="No thanks", style=discord.ButtonStyle.secondary, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._decline_action(interaction)


class QuizNavigationView(discord.ui.View):
    """Buttons shown after a quiz assessment: continue, explain, or stop."""

    def __init__(self, concept_id: int, quality: int, message_handler: Callable[..., Awaitable]):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.concept_id = concept_id
        self.quality = quality
        self.message_handler = message_handler
        self.clicked = False

        if quality >= 3:
            self.add_item(_QuizNextDueButton(self, style=discord.ButtonStyle.primary))
            self.add_item(_QuizAgainButton(self, style=discord.ButtonStyle.secondary))
        else:
            self.add_item(_QuizExplainButton(self, style=discord.ButtonStyle.primary))
            self.add_item(_QuizAgainButton(self, style=discord.ButtonStyle.secondary))
            self.add_item(_QuizNextDueButton(self, style=discord.ButtonStyle.secondary))
        self.add_item(_QuizDoneButton(self))

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()


class _QuizAgainButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView, style: discord.ButtonStyle):
        super().__init__(label="Quiz again", emoji="🔄", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        try:
            from bot.messages import send_discord_result

            with state.current_user_scope(_interaction_user_id(interaction)):
                async with interaction.channel.typing():
                    payload = await handle_chat_action(
                        {
                            "kind": "quiz_followup",
                            "followup": "quiz_again",
                            "concept_id": self.parent_view.concept_id,
                        },
                        author=str(interaction.user),
                        source="discord",
                    )
            await send_discord_result(
                interaction.followup.send,
                payload.get("message", ""),
                self.parent_view.message_handler,
                actions=payload.get("actions"),
            )
        except Exception as e:
            logger.error(f"QuizAgain callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


class _QuizNextDueButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView, style: discord.ButtonStyle):
        super().__init__(label="Next due", emoji="⏭️", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        try:
            from bot.messages import send_discord_result

            with state.current_user_scope(_interaction_user_id(interaction)):
                async with interaction.channel.typing():
                    payload = await handle_chat_action(
                        {
                            "kind": "quiz_followup",
                            "followup": "next_due",
                        },
                        author=str(interaction.user),
                        source="discord",
                    )
            await send_discord_result(
                interaction.followup.send,
                payload.get("message", ""),
                self.parent_view.message_handler,
                actions=payload.get("actions"),
            )
        except Exception as e:
            logger.error(f"QuizNextDue callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


class _QuizExplainButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView, style: discord.ButtonStyle):
        super().__init__(label="Explain", emoji="💡", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        try:
            from bot.messages import send_discord_result

            with state.current_user_scope(_interaction_user_id(interaction)):
                async with interaction.channel.typing():
                    payload = await handle_chat_action(
                        {
                            "kind": "quiz_followup",
                            "followup": "explain",
                            "concept_id": self.parent_view.concept_id,
                        },
                        author=str(interaction.user),
                        source="discord",
                    )
            await send_discord_result(
                interaction.followup.send,
                payload.get("message", ""),
                self.parent_view.message_handler,
                actions=payload.get("actions"),
            )
        except Exception as e:
            logger.error(f"QuizExplain callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.parent_view.stop()


class _QuizDoneButton(discord.ui.Button):
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


class QuizQuestionView(discord.ui.View):
    """Optional button shown with quiz questions: allows skipping if eligible."""

    def __init__(self, concept_id: int, message_handler: Callable[..., Awaitable], show_skip: bool = True):
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
    return bool(concept and concept.get("review_count", 0) >= 2)


class _QuizSkipButton(discord.ui.Button):
    def __init__(self, parent_view: QuizQuestionView):
        super().__init__(label="I know this", emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.clicked:
            return
        self.parent_view.clicked = True
        self.parent_view._disable_all()
        await interaction.response.edit_message(view=self.parent_view)

        try:
            with state.current_user_scope(_interaction_user_id(interaction)):
                async with state.pipeline_serialized():
                    result = execute_skip_quiz_action(
                        self.parent_view.concept_id,
                        user_id=_interaction_user_id(interaction),
                        source="discord",
                    )
                    if "error" in result:
                        await interaction.followup.send(f"⚠️ {result['error']}")
                        self.parent_view.stop()
                        return
                    state.mark_user_activity()
                    nav_view = QuizNavigationView(
                        concept_id=result["concept_id"],
                        quality=result["quality"],
                        message_handler=self.parent_view.message_handler,
                    )
            await interaction.followup.send(result["message"], view=nav_view)
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
    if not response or not response.strip():
        response = "✅ No concepts due right now!"

    from bot.messages import _send_quiz_prompt

    normalized_meta = dict(quiz_meta) if quiz_meta is not None else {}
    quiz_cid = normalized_meta.get("concept_id")
    if quiz_cid is None:
        fallback_quiz_cid = db.get_session("quiz_anchor_concept_id")
        if fallback_quiz_cid is not None:
            quiz_cid = int(fallback_quiz_cid)

    if quiz_meta is not None or quiz_cid is not None:
        await _send_quiz_prompt(
            interaction.followup.send,
            response,
            int(quiz_cid) if quiz_cid is not None else None,
            message_handler,
            heading=normalized_meta.get("heading"),
            show_skip=normalized_meta.get("show_skip"),
        )
        if quiz_cid is not None:
            register_interactive_review_delivery(int(quiz_cid), response.strip())
        return

    await interaction.followup.send(truncate_for_discord(response))


class PreferenceUpdateView(discord.ui.View):
    """Apply or reject a preference edit proposal."""

    def __init__(self, action_data: dict):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.action_data = action_data
        self.decided = False

    @discord.ui.button(label="Apply", style=discord.ButtonStyle.success, emoji="✅")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.decided:
            return
        self.decided = True
        self._disable_all()
        try:
            with state.current_user_scope(_interaction_user_id(interaction)):
                payload = await confirm_chat_action(self.action_data, source="discord")
                result = payload.get("message") or "Preferences updated."
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
            with state.current_user_scope(_interaction_user_id(interaction)):
                payload = await decline_chat_action(self.action_data, source="discord")
                result = payload.get("message") or "Update discarded."
            await interaction.response.edit_message(content=result, view=self)
        except discord.errors.NotFound:
            pass
        self.stop()

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        self._disable_all()
