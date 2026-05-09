"""Discord UI views for confirmation flows and quiz actions."""

import logging
from datetime import datetime
from typing import Awaitable, Callable

import discord

import db
from services import state
from services.chat_actions import resolve_lightweight_confirmation
from services.chat_quiz import build_quiz_followup_prompt
from services.chat_session import confirm_chat_action, decline_chat_action, handle_chat_action
from services.formatting import format_quiz_metadata, truncate_for_discord, truncate_with_suffix
from services.review_state import get_pending_review, register_interactive_review_delivery

logger = logging.getLogger("views")

VIEW_TIMEOUT = 86400


def _interaction_user_id(interaction: discord.Interaction) -> str:
    return state.get_local_user_id()


class _ProposalDecisionView(discord.ui.View):
    """Shared timeout and disable lifecycle for proposal-backed Discord views."""

    def __init__(self, proposal_id: int):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposal_id = proposal_id
        self.proposal_user_id = state.get_current_user()

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def on_timeout(self):
        with state.current_user_scope(self.proposal_user_id):
            db.delete_proposal(self.proposal_id, user_id=self.proposal_user_id)
        self._disable_all()

    async def _run_decision_payloads(
        self,
        *,
        approved_payload: dict | None = None,
        rejected_payload: dict | None = None,
    ) -> list[str]:
        result_parts = []

        with state.current_user_scope(self.proposal_user_id):
            for payload in (approved_payload, rejected_payload):
                if not payload:
                    continue
                response = await handle_chat_action(payload, source="discord")
                if response.get("message"):
                    result_parts.append(response["message"])

        return result_parts

    async def _render_decision_result(
        self,
        interaction: discord.Interaction,
        *,
        result_parts: list[str],
        empty_message: str,
    ):
        self._disable_all()
        result_text = "\n\n".join(result_parts) if result_parts else empty_message
        try:
            await interaction.message.edit(content=truncate_for_discord(result_text), view=self)
        except discord.errors.NotFound:
            pass
        self.stop()


class DedupConfirmView(_ProposalDecisionView):
    """View with per-group approve/reject buttons plus bulk actions."""

    def __init__(self, proposal_id: int, groups: list[dict]):
        super().__init__(proposal_id)
        self.groups = groups
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(groups))}

        self.add_item(_BulkDecisionButton(True, on_decide=self._apply_all_group_decisions))
        self.add_item(_BulkDecisionButton(False, on_decide=self._apply_all_group_decisions))

        max_groups = min(len(groups), 10)
        for i in range(max_groups):
            row = min(4, (i // 2) + 1)
            approve = _IndexedDecisionButton(
                i,
                True,
                custom_id=f"dedup_approve_{i}",
                row=row,
                on_decide=self._apply_group_decision,
            )
            reject = _IndexedDecisionButton(
                i,
                False,
                custom_id=f"dedup_reject_{i}",
                row=row,
                on_decide=self._apply_group_decision,
            )
            approve.counterpart = reject
            reject.counterpart = approve
            self.add_item(approve)
            self.add_item(reject)

    async def _finalize(self, interaction: discord.Interaction):
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending:
            return

        approved_ids = [f"dedup-{i}" for i, decision in self.decisions.items() if decision is True]
        rejected_ids = [f"dedup-{i}" for i, decision in self.decisions.items() if decision is False]
        result_parts = await self._run_decision_payloads(
            approved_payload={
                "kind": "apply_dedup_groups",
                "proposal_id": self.proposal_id,
                "proposal_item_ids": approved_ids,
            }
            if approved_ids
            else None,
            rejected_payload={
                "kind": "reject_proposals",
                "proposal_id": self.proposal_id,
                "proposal_item_ids": rejected_ids,
                "source": "dedup",
            }
            if rejected_ids
            else None,
        )
        await self._render_decision_result(
            interaction,
            result_parts=result_parts,
            empty_message="No merges executed.",
        )

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

    async def _apply_group_decision(
        self,
        interaction: discord.Interaction,
        group_idx: int,
        approved: bool,
    ):
        self.decisions[group_idx] = approved
        status = self._get_status_text()
        await interaction.response.edit_message(
            content=truncate_for_discord(f"🔄 **Dedup Proposals**\n\n{status}"),
            view=self,
        )
        await self._finalize(interaction)

    async def _apply_all_group_decisions(
        self,
        interaction: discord.Interaction,
        approved: bool,
    ):
        for index in self.decisions:
            self.decisions[index] = approved
        await interaction.response.defer()
        await self._finalize(interaction)


class _BulkDecisionButton(discord.ui.Button):
    def __init__(
        self,
        approved: bool,
        *,
        on_decide: Callable[[discord.Interaction, bool], Awaitable[None]],
    ):
        super().__init__(
            label="Approve All" if approved else "Reject All",
            style=discord.ButtonStyle.success if approved else discord.ButtonStyle.danger,
            emoji="✅" if approved else "❌",
            row=0,
        )
        self.approved = approved
        self.on_decide = on_decide

    async def callback(self, interaction: discord.Interaction):
        await self.on_decide(interaction, self.approved)


class _IndexedDecisionButton(discord.ui.Button):
    def __init__(
        self,
        decision_index: int,
        approved: bool,
        *,
        custom_id: str,
        row: int,
        on_decide: Callable[[discord.Interaction, int, bool], Awaitable[None]],
    ):
        super().__init__(
            label=f"{'✅' if approved else '❌'} {decision_index + 1}",
            style=discord.ButtonStyle.success if approved else discord.ButtonStyle.danger,
            custom_id=custom_id,
            row=row,
        )
        self.decision_index = decision_index
        self.approved = approved
        self.on_decide = on_decide
        self.counterpart = None

    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        if self.counterpart is not None:
            self.counterpart.disabled = True
        await self.on_decide(interaction, self.decision_index, self.approved)


class ProposedActionsView(_ProposalDecisionView):
    """View for confirming proposed LLM actions."""

    def __init__(
        self,
        proposal_id: int,
        actions: list[dict],
        *,
        source: str = "maintenance",
    ):
        super().__init__(proposal_id)
        self.actions = actions
        self.source = source
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(actions))}
        self._finalizing = False

        self.add_item(_BulkDecisionButton(True, on_decide=self._apply_all_action_decisions))
        self.add_item(_BulkDecisionButton(False, on_decide=self._apply_all_action_decisions))

        max_actions = min(len(actions), 10)
        for index in range(max_actions):
            row = min(4, (index // 2) + 1)
            approve = _IndexedDecisionButton(
                index,
                True,
                custom_id=f"maint_approve_{index}",
                row=row,
                on_decide=self._apply_action_decision,
            )
            reject = _IndexedDecisionButton(
                index,
                False,
                custom_id=f"maint_reject_{index}",
                row=row,
                on_decide=self._apply_action_decision,
            )
            approve.counterpart = reject
            reject.counterpart = approve
            self.add_item(approve)
            self.add_item(reject)

    async def _finalize(self, interaction: discord.Interaction):
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending or self._finalizing:
            return
        self._finalizing = True

        approved_ids = [f"{self.source}-{i}" for i, decision in self.decisions.items() if decision is True]
        rejected_ids = [f"{self.source}-{i}" for i, decision in self.decisions.items() if decision is False]
        result_parts = await self._run_decision_payloads(
            approved_payload={
                "kind": "apply_maintenance_actions",
                "proposal_id": self.proposal_id,
                "proposal_item_ids": approved_ids,
                "source": self.source,
            }
            if approved_ids
            else None,
            rejected_payload={
                "kind": "reject_proposals",
                "proposal_id": self.proposal_id,
                "proposal_item_ids": rejected_ids,
                "source": self.source,
            }
            if rejected_ids
            else None,
        )
        await self._render_decision_result(
            interaction,
            result_parts=result_parts,
            empty_message="No actions executed.",
        )

    async def _apply_action_decision(
        self,
        interaction: discord.Interaction,
        action_index: int,
        approved: bool,
    ):
        self.decisions[action_index] = approved
        await interaction.response.edit_message(view=self)
        await self._finalize(interaction)

    async def _apply_all_action_decisions(
        self,
        interaction: discord.Interaction,
        approved: bool,
    ):
        for index in self.decisions:
            self.decisions[index] = approved
        await interaction.response.defer()
        await self._finalize(interaction)


class _ActionButton(discord.ui.Button):
    def __init__(
        self,
        *,
        label: str,
        style: discord.ButtonStyle,
        emoji: str,
        on_click: Callable[[discord.Interaction], Awaitable[None]],
    ):
        super().__init__(label=label, style=style, emoji=emoji)
        self.on_click = on_click

    async def callback(self, interaction: discord.Interaction):
        await self.on_click(interaction)


class _LightweightConfirmView(discord.ui.View):
    def __init__(
        self,
        action_data: dict,
        on_resolved: Callable | None = None,
        *,
        approve_label: str,
        decline_label: str = "No thanks",
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.action_data = action_data
        self.decided = False
        self.on_resolved = on_resolved
        self.add_item(
            _ActionButton(
                label=approve_label,
                style=discord.ButtonStyle.success,
                emoji="✅",
                on_click=self._accept_action,
            )
        )
        self.add_item(
            _ActionButton(
                label=decline_label,
                style=discord.ButtonStyle.secondary,
                emoji="❌",
                on_click=self._decline_action,
            )
        )

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
        super().__init__(
            action_data,
            on_resolved=on_resolved,
            approve_label="Add concept",
        )


class SuggestTopicConfirmView(_LightweightConfirmView):
    """Accept or decline adding a suggested topic."""

    def __init__(self, action_data: dict, on_resolved: Callable | None = None):
        super().__init__(
            action_data,
            on_resolved=on_resolved,
            approve_label="Add topic",
        )


class _SingleUseQuizView(discord.ui.View):
    """Shared single-click lifecycle for Discord quiz views."""

    def __init__(self):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.clicked = False

    def _disable_all(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

    async def _start_action(
        self,
        interaction: discord.Interaction,
        *,
        content: str | None = None,
        ignore_not_found: bool = False,
    ) -> bool:
        if self.clicked:
            return False
        self.clicked = True
        self._disable_all()

        kwargs = {"view": self}
        if content is not None:
            kwargs["content"] = content

        try:
            await interaction.response.edit_message(**kwargs)
        except discord.errors.NotFound:
            if not ignore_not_found:
                raise
        return True

    async def on_timeout(self):
        self._disable_all()


class QuizNavigationView(_SingleUseQuizView):
    """Buttons shown after a quiz assessment: continue, explain, or stop."""

    def __init__(self, concept_id: int, quality: int, message_handler: Callable[..., Awaitable]):
        super().__init__()
        self.concept_id = concept_id
        self.quality = quality
        self.message_handler = message_handler

        if quality >= 3:
            self.add_item(_QuizNextDueButton(self, style=discord.ButtonStyle.primary))
            self.add_item(_QuizAgainButton(self, style=discord.ButtonStyle.secondary))
        else:
            self.add_item(_QuizExplainButton(self, style=discord.ButtonStyle.primary))
            self.add_item(_QuizAgainButton(self, style=discord.ButtonStyle.secondary))
            self.add_item(_QuizNextDueButton(self, style=discord.ButtonStyle.secondary))
        self.add_item(_QuizDoneButton(self))

    async def _run_followup_action(
        self,
        interaction: discord.Interaction,
        *,
        followup: str,
        include_concept_id: bool,
        error_label: str,
    ):
        if not await self._start_action(interaction):
            return

        try:
            from bot.messages import send_discord_result

            action = {
                "kind": "quiz_followup",
                "followup": followup,
            }
            if include_concept_id:
                action["concept_id"] = self.concept_id

            with state.current_user_scope(_interaction_user_id(interaction)):
                async with interaction.channel.typing():
                    payload = await handle_chat_action(
                        action,
                        author=str(interaction.user),
                        source="discord",
                    )
            await send_discord_result(
                interaction.followup.send,
                payload.get("message", ""),
                self.message_handler,
                actions=payload.get("actions"),
            )
        except Exception as e:
            logger.error(f"{error_label} callback error: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"⚠️ Error: {e}")
            except discord.errors.NotFound:
                pass
        self.stop()


class _QuizAgainButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView, style: discord.ButtonStyle):
        super().__init__(label="Quiz again", emoji="🔄", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view._run_followup_action(
            interaction,
            followup="quiz_again",
            include_concept_id=True,
            error_label="QuizAgain",
        )


class _QuizNextDueButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView, style: discord.ButtonStyle):
        super().__init__(label="Next due", emoji="⏭️", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view._run_followup_action(
            interaction,
            followup="next_due",
            include_concept_id=False,
            error_label="QuizNextDue",
        )


class _QuizExplainButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView, style: discord.ButtonStyle):
        super().__init__(label="Explain", emoji="💡", style=style, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view._run_followup_action(
            interaction,
            followup="explain",
            include_concept_id=True,
            error_label="QuizExplain",
        )


class _QuizDoneButton(discord.ui.Button):
    def __init__(self, parent_view: QuizNavigationView):
        super().__init__(label="Done", emoji="✋", style=discord.ButtonStyle.secondary, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        original = interaction.message.content or ""
        if not await self.parent_view._start_action(
            interaction,
            content=truncate_with_suffix(original, "\n\n✋ Quiz session ended."),
            ignore_not_found=True,
        ):
            return
        self.parent_view.stop()


class QuizQuestionView(_SingleUseQuizView):
    """Optional button shown with quiz questions: allows skipping if eligible."""

    def __init__(self, concept_id: int, message_handler: Callable[..., Awaitable], show_skip: bool = True):
        super().__init__()
        self.concept_id = concept_id
        self.message_handler = message_handler
        if show_skip:
            self.add_item(_QuizSkipButton(self))


def should_show_quiz_skip_button(concept: dict | None) -> bool:
    return bool(concept and concept.get("review_count", 0) >= 2)


class _QuizSkipButton(discord.ui.Button):
    def __init__(self, parent_view: QuizQuestionView):
        super().__init__(label="I know this", emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if not await self.parent_view._start_action(interaction):
            return

        try:
            with state.current_user_scope(_interaction_user_id(interaction)):
                payload = await handle_chat_action(
                    {"kind": "skip_quiz", "concept_id": self.parent_view.concept_id},
                    author=str(interaction.user),
                    source="discord",
                )
                if payload.get("type") == "error":
                    await interaction.followup.send(f"⚠️ {payload.get('message', '')}")
                    self.parent_view.stop()
                    return
                state.mark_user_activity()

            from bot.messages import send_discord_result

            await send_discord_result(
                interaction.followup.send,
                payload.get("message", ""),
                self.parent_view.message_handler,
                actions=payload.get("actions"),
            )
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


class PreferenceUpdateView(_LightweightConfirmView):
    """Apply or reject a preference edit proposal."""

    def __init__(self, action_data: dict):
        discord.ui.View.__init__(self, timeout=VIEW_TIMEOUT)
        self.action_data = action_data
        self.decided = False
        self.on_resolved = None
        self.add_item(
            _ActionButton(
                label="Apply",
                style=discord.ButtonStyle.success,
                emoji="✅",
                on_click=lambda interaction: self._resolve_preference_action(interaction, approve=True),
            )
        )
        self.add_item(
            _ActionButton(
                label="Reject",
                style=discord.ButtonStyle.danger,
                emoji="❌",
                on_click=lambda interaction: self._resolve_preference_action(interaction, approve=False),
            )
        )

    async def _resolve_preference_action(
        self,
        interaction: discord.Interaction,
        *,
        approve: bool,
    ):
        if self.decided:
            return
        self.decided = True
        self._disable_all()

        result = "Preferences updated." if approve else "Update discarded."
        try:
            with state.current_user_scope(_interaction_user_id(interaction)):
                payload = await (
                    confirm_chat_action(self.action_data, source="discord")
                    if approve
                    else decline_chat_action(self.action_data, source="discord")
                )
                result = payload.get("message") or result
        except Exception as e:
            if not approve:
                raise
            logger.error(f"PreferenceUpdateView apply error: {e}", exc_info=True)
            result = f"⚠️ Failed to update preferences: {e}"
        try:
            await interaction.response.edit_message(content=result, view=self)
        except discord.errors.NotFound:
            pass
        self._finish_resolution()
