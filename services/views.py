"""
Discord UI views for confirmation flows (dedup, maintenance, concept addition).
Uses discord.py's Button/View components for safe, mobile-friendly interactions.

See DEVNOTES.md §6 for design rationale.
"""

import logging
from typing import Callable, Awaitable

import discord

import db
from services.dedup import execute_dedup_merges

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
            keep_concept = db.get_concept(groups[i]['keep'])
            label = keep_concept['title'][:30] if keep_concept else f"Group {i+1}"
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
            await interaction.message.edit(content=result_text, view=self)
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
            keep_concept = db.get_concept(g['keep'])
            keep_title = keep_concept['title'] if keep_concept else f"#{g['keep']}"
            decision = self.decisions.get(i)
            if decision is True:
                status = "✅ Approved"
            elif decision is False:
                status = "❌ Rejected"
            else:
                status = "⏳ Pending"
            lines.append(f"**{i+1}.** {keep_title} — {status}")
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
            if (isinstance(item, RejectGroupButton)
                    and item.group_idx == self.group_idx):
                item.disabled = True
                break

        status = self.parent_view._get_status_text()
        await interaction.response.edit_message(
            content=f"🔄 **Dedup Proposals**\n\n{status}", view=self.parent_view
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
            if (isinstance(item, ApproveGroupButton)
                    and item.group_idx == self.group_idx):
                item.disabled = True
                break

        status = self.parent_view._get_status_text()
        await interaction.response.edit_message(
            content=f"🔄 **Dedup Proposals**\n\n{status}", view=self.parent_view
        )
        await self.parent_view._finalize(interaction)


# ============================================================================
# Maintenance confirmation view
# ============================================================================

class MaintenanceConfirmView(discord.ui.View):
    """View for confirming destructive maintenance actions.
    Shows proposed actions with approve/reject buttons."""

    def __init__(self, proposal_id: int, actions: list[dict],
                 execute_fn: Callable[[list[dict]], Awaitable[list[str]]]):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.proposal_id = proposal_id
        self.actions = actions
        self.execute_fn = execute_fn
        self.decisions: dict[int, bool | None] = {i: None for i in range(len(actions))}

        self.add_item(MaintenanceApproveAllButton(self))
        self.add_item(MaintenanceRejectAllButton(self))

        max_actions = min(len(actions), 10)
        for i in range(max_actions):
            action_label = actions[i].get('action', 'unknown')[:20]
            self.add_item(MaintenanceApproveButton(self, i, action_label))
            self.add_item(MaintenanceRejectButton(self, i, action_label))

    async def _finalize(self, interaction: discord.Interaction):
        pending = [i for i, d in self.decisions.items() if d is None]
        if pending:
            return

        approved = [self.actions[i] for i, d in self.decisions.items() if d]
        rejected_count = sum(1 for d in self.decisions.values() if not d)

        result_parts = []
        if approved:
            summaries = await self.execute_fn(approved)
            if summaries:
                result_parts.append(
                    f"✅ **Executed {len(summaries)} action(s):**\n"
                    + "\n".join(f"• {s}" for s in summaries)
                )

        if rejected_count:
            result_parts.append(f"❌ Rejected {rejected_count} action(s).")

        db.delete_proposal(self.proposal_id)
        self._disable_all()

        result_text = "\n\n".join(result_parts) if result_parts else "No actions executed."
        try:
            await interaction.message.edit(content=result_text, view=self)
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


class MaintenanceApproveAllButton(discord.ui.Button):
    def __init__(self, parent_view: MaintenanceConfirmView):
        super().__init__(label="Approve All", style=discord.ButtonStyle.success,
                         emoji="✅", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for i in self.parent_view.decisions:
            self.parent_view.decisions[i] = True
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class MaintenanceRejectAllButton(discord.ui.Button):
    def __init__(self, parent_view: MaintenanceConfirmView):
        super().__init__(label="Reject All", style=discord.ButtonStyle.danger,
                         emoji="❌", row=0)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        for i in self.parent_view.decisions:
            self.parent_view.decisions[i] = False
        await interaction.response.defer()
        await self.parent_view._finalize(interaction)


class MaintenanceApproveButton(discord.ui.Button):
    def __init__(self, parent_view: MaintenanceConfirmView, idx: int, label: str):
        row = min(4, (idx // 2) + 1)
        super().__init__(label=f"✅ {idx + 1}", style=discord.ButtonStyle.success,
                         custom_id=f"maint_approve_{idx}", row=row)
        self.parent_view = parent_view
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.decisions[self.idx] = True
        self.disabled = True
        for item in self.parent_view.children:
            if isinstance(item, MaintenanceRejectButton) and item.idx == self.idx:
                item.disabled = True
                break
        await interaction.response.edit_message(view=self.parent_view)
        await self.parent_view._finalize(interaction)


class MaintenanceRejectButton(discord.ui.Button):
    def __init__(self, parent_view: MaintenanceConfirmView, idx: int, label: str):
        row = min(4, (idx // 2) + 1)
        super().__init__(label=f"❌ {idx + 1}", style=discord.ButtonStyle.danger,
                         custom_id=f"maint_reject_{idx}", row=row)
        self.parent_view = parent_view
        self.idx = idx

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.decisions[self.idx] = False
        self.disabled = True
        for item in self.parent_view.children:
            if isinstance(item, MaintenanceApproveButton) and item.idx == self.idx:
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

    def __init__(self, action_data: dict, on_resolved: callable | None = None):
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
        action = self.action_data.get('action', 'add_concept')
        params = self.action_data.get('params', {})
        msg_type, result = execute_action(action, params)

        if msg_type == 'error':
            note = f"\n\n⚠️ Could not add concept: {result}"
        else:
            note = f"\n\n✅ {result}"

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(content=original + note, view=self)
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

        try:
            original = interaction.message.content or ""
            await interaction.response.edit_message(content=original, view=self)
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
