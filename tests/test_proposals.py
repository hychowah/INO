"""Tests for user-scoped pending proposal persistence."""

from unittest.mock import AsyncMock, patch

import pytest

import db
from bot import commands as bot_commands
from services import state
from services.views import DedupConfirmView, ProposedActionsView


def test_pending_proposal_is_scoped_by_explicit_user(test_db):
    proposal_a = db.save_proposal("dedup", [{"keep": 1, "merge": [2]}], user_id="user_a")
    proposal_b = db.save_proposal("dedup", [{"keep": 3, "merge": [4]}], user_id="user_b")

    pending_a = db.get_pending_proposal("dedup", user_id="user_a")
    pending_b = db.get_pending_proposal("dedup", user_id="user_b")

    assert pending_a is not None
    assert pending_b is not None
    assert pending_a["id"] == proposal_a
    assert pending_b["id"] == proposal_b
    assert pending_a["user_id"] == "user_a"
    assert pending_b["user_id"] == "user_b"


def test_get_proposal_uses_context_user_by_default(test_db):
    proposal_id = db.save_proposal("maintenance", [{"action": "delete_topic", "params": {"topic_id": 1}}], user_id="ctx_user")

    previous_user = state.get_current_user()
    state.set_current_user("ctx_user")
    try:
        proposal = db.get_proposal(proposal_id)
        assert proposal is not None
        assert proposal["user_id"] == "ctx_user"
        assert proposal["proposal_type"] == "maintenance"
    finally:
        state.set_current_user(previous_user)


def test_get_proposal_hides_other_users_proposal(test_db):
    proposal_id = db.save_proposal("taxonomy", [{"action": "link_topics", "params": {"parent_id": 1, "child_id": 2}}], user_id="owner")

    assert db.get_proposal(proposal_id, user_id="other") is None
    assert db.get_pending_proposal("taxonomy", user_id="other") is None


def test_delete_proposal_only_removes_matching_user(test_db):
    proposal_a = db.save_proposal("dedup", [{"keep": 1, "merge": [2]}], user_id="user_a")
    proposal_b = db.save_proposal("dedup", [{"keep": 3, "merge": [4]}], user_id="user_b")

    db.delete_proposal(proposal_a, user_id="user_b")

    assert db.get_proposal(proposal_a, user_id="user_a") is not None
    assert db.get_proposal(proposal_b, user_id="user_b") is not None

    db.delete_proposal(proposal_a, user_id="user_a")
    assert db.get_proposal(proposal_a, user_id="user_a") is None


def test_update_proposal_payload_replaces_payload_for_matching_user(test_db):
    proposal_id = db.save_proposal(
        "maintenance",
        [
            {"action": "update_topic", "_proposal_item_id": "maintenance-0"},
            {"action": "delete_topic", "_proposal_item_id": "maintenance-1"},
        ],
        user_id="owner",
    )

    db.update_proposal_payload(
        proposal_id,
        [{"action": "delete_topic", "_proposal_item_id": "maintenance-1"}],
        user_id="owner",
    )

    proposal = db.get_proposal(proposal_id, user_id="owner")
    assert proposal is not None
    assert proposal["payload"] == [
        {"action": "delete_topic", "_proposal_item_id": "maintenance-1"}
    ]


class _FakeMessage:
    def __init__(self):
        self.edit = AsyncMock()


class _FakeInteraction:
    def __init__(self):
        self.message = _FakeMessage()


class _AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _MockChannel:
    def typing(self):
        return _AsyncNullContext()


class _MockAuthor:
    def __str__(self):
        return "test-author"


class _MockCtx:
    def __init__(self):
        self.interaction = None
        self.channel = _MockChannel()
        self.author = _MockAuthor()
        self.send = AsyncMock()


@pytest.mark.anyio
async def test_dedup_view_finalizes_through_shared_chat_action(test_db):
    proposal_id = db.save_proposal("dedup", [{"keep": 1, "merge": [2]}], user_id="owner")
    previous_user = state.get_current_user()
    state.set_current_user("owner")
    try:
        view = DedupConfirmView(proposal_id, [{"keep": 1, "merge": [2]}])
    finally:
        state.set_current_user(previous_user)

    view.decisions[0] = True
    interaction = _FakeInteraction()

    with patch("services.views.handle_chat_action", new=AsyncMock(return_value={"message": "Applied dedup changes:\n- merged"})) as action_mock:
        await view._finalize(interaction)

    action_mock.assert_awaited_once_with(
        {
            "kind": "apply_dedup_groups",
            "proposal_id": proposal_id,
            "proposal_item_ids": ["dedup-0"],
        },
        source="discord",
    )
    interaction.message.edit.assert_awaited_once()


@pytest.mark.anyio
async def test_proposed_actions_view_finalizes_through_shared_chat_action(test_db):
    proposal_id = db.save_proposal(
        "maintenance",
        [{"action": "update_topic", "params": {"topic_id": 1}}],
        user_id="owner",
    )
    previous_user = state.get_current_user()
    state.set_current_user("owner")
    try:
        view = ProposedActionsView(
            proposal_id,
            [{"action": "update_topic", "params": {"topic_id": 1}}],
            source="maintenance",
        )
    finally:
        state.set_current_user(previous_user)

    view.decisions[0] = False
    interaction = _FakeInteraction()

    with patch("services.views.handle_chat_action", new=AsyncMock(return_value={"message": "Rejected 1 proposal(s)."})) as action_mock:
        await view._finalize(interaction)

    action_mock.assert_awaited_once_with(
        {
            "kind": "reject_proposals",
            "proposal_id": proposal_id,
            "proposal_item_ids": ["maintenance-0"],
            "source": "maintenance",
        },
        source="discord",
    )
    interaction.message.edit.assert_awaited_once()


@pytest.mark.anyio
async def test_maintain_command_uses_shared_maintenance_request_for_proposals(test_db):
    ctx = _MockCtx()
    dedup_id = db.save_proposal("dedup", [{"keep": 1, "merge": [2]}])
    maintenance_id = db.save_proposal("maintenance", [{"action": "update_topic", "params": {"topic_id": 1}}])
    payload = {
        "message": "Shared maintenance summary",
        "actions": [
            {
                "type": "proposal_review",
                "title": "Dedup proposals",
                "items": [
                    {
                        "id": "dedup-0",
                        "buttons": [
                            {"action": {"kind": "apply_dedup_groups", "proposal_id": dedup_id, "proposal_item_ids": ["dedup-0"]}}
                        ],
                    }
                ],
            },
            {
                "type": "proposal_review",
                "title": "Maintenance proposals",
                "items": [
                    {
                        "id": "maintenance-0",
                        "buttons": [
                            {"action": {"kind": "apply_maintenance_actions", "proposal_id": maintenance_id, "proposal_item_ids": ["maintenance-0"], "source": "maintenance"}}
                        ],
                    }
                ],
            },
        ],
    }

    with (
        patch.object(bot_commands.config, "MAINTENANCE_MODE_ENABLED", True),
        patch("bot.commands.send_long", new=AsyncMock()) as send_long_mock,
        patch("bot.commands.chat_session.handle_maintenance_request", new=AsyncMock(return_value=payload)) as handle_mock,
    ):
        await bot_commands.maintain_command.callback(ctx)

    handle_mock.assert_awaited_once_with()
    send_long_mock.assert_awaited_once_with(ctx, "Shared maintenance summary")
    assert len(ctx.send.await_args_list) == 2
    assert isinstance(ctx.send.await_args_list[0].kwargs["view"], DedupConfirmView)
    assert isinstance(ctx.send.await_args_list[1].kwargs["view"], ProposedActionsView)


@pytest.mark.anyio
async def test_reorganize_command_uses_shared_reorganize_request_for_proposals(test_db):
    ctx = _MockCtx()
    proposal_id = db.save_proposal(
        "taxonomy",
        [{"action": "link_topics", "params": {"parent_id": 1, "child_id": 2}}],
    )
    payload = {
        "message": "Shared taxonomy summary",
        "actions": [
            {
                "type": "proposal_review",
                "title": "Taxonomy proposals",
                "items": [
                    {
                        "id": "taxonomy-0",
                        "buttons": [
                            {"action": {"kind": "apply_maintenance_actions", "proposal_id": proposal_id, "proposal_item_ids": ["taxonomy-0"], "source": "taxonomy"}}
                        ],
                    }
                ],
            }
        ],
    }

    with (
        patch("bot.commands.send_long", new=AsyncMock()) as send_long_mock,
        patch("bot.commands.chat_session.handle_reorganize_request", new=AsyncMock(return_value=payload)) as handle_mock,
    ):
        await bot_commands.reorganize_command.callback(ctx)

    handle_mock.assert_awaited_once_with()
    send_long_mock.assert_awaited_once_with(ctx, "Shared taxonomy summary")
    ctx.send.assert_awaited_once()
    assert isinstance(ctx.send.await_args.kwargs["view"], ProposedActionsView)
