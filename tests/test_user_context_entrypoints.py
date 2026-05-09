"""Focused tests for adapter-level current-user scoping."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api import app
from bot import commands
from bot import events
from bot import handler
from services import state
from api import auth as api_auth
from services import chat_session
from services import views


@pytest.fixture
async def client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_current_user_scope_restores_previous_user():
    previous_user = state.get_current_user()

    with state.current_user_scope("scoped-user"):
        assert state.get_current_user() == "scoped-user"

    assert state.get_current_user() == previous_user


@pytest.mark.anyio
async def test_handle_user_message_sets_context_from_explicit_user_id(test_db):
    seen = {}
    previous_user = state.get_current_user()

    async def fake_fetch_loop(mode, text, author):
        seen["user"] = state.get_current_user()
        seen["author"] = author
        return "raw"

    with (
        patch.object(handler, "_ensure_db", return_value=None),
        patch("bot.handler.call_with_fetch_loop", new=AsyncMock(side_effect=fake_fetch_loop)),
        patch("bot.handler.parse_llm_response", return_value=("REPLY", "raw", None)),
        patch("bot.handler.pipeline.execute_llm_response", new=AsyncMock(return_value="REPLY: done")),
        patch("bot.handler.process_output", return_value=("reply", "done")),
    ):
        message, pending_action, assess_meta, quiz_meta = await handler._handle_user_message(
            "hello",
            "Display Name",
            user_id="discord-user-42",
        )

    assert message == "done"
    assert pending_action is None
    assert assess_meta is None
    assert quiz_meta is None
    assert seen == {"user": "discord-user-42", "author": "Display Name"}
    assert state.get_current_user() == previous_user


@pytest.mark.anyio
async def test_api_chat_uses_explicit_local_user_scope(client):
    async def fake_handle_chat_message(message, author, source):
        return {
            "type": "reply",
            "message": f"{state.get_current_user()}|{author}|{source}",
            "pending_action": None,
        }

    previous_user = state.get_current_user()
    with patch("api.routes.chat.handle_chat_message", new=AsyncMock(side_effect=fake_handle_chat_message)):
        resp = await client.post("/api/chat", json={"message": "hello"})

    assert resp.status_code == 200
    assert resp.json() == {
        "type": "reply",
        "message": f"{api_auth.local_api_user_id()}|solo_user|api",
        "pending_action": None,
    }
    assert state.get_current_user() == previous_user


@pytest.mark.anyio
async def test_api_non_chat_route_uses_request_user_scope(client):
    seen = {}
    previous_user = state.get_current_user()

    def fake_get_topics():
        seen["user"] = state.get_current_user()
        return []

    with patch("api.routes.topics.db.get_hierarchical_topic_map", side_effect=fake_get_topics):
        resp = await client.get("/api/topics")

    assert resp.status_code == 200
    assert resp.json() == []
    assert seen == {"user": api_auth.local_api_user_id()}
    assert state.get_current_user() == previous_user


@pytest.mark.anyio
async def test_api_chat_uses_explicit_header_user_scope(client):
    async def fake_handle_chat_message(message, author, source):
        return {
            "type": "reply",
            "message": f"{state.get_current_user()}|{author}|{source}",
            "pending_action": None,
        }

    previous_user = state.get_current_user()
    with patch("api.routes.chat.handle_chat_message", new=AsyncMock(side_effect=fake_handle_chat_message)):
        resp = await client.post(
            "/api/chat",
            json={"message": "hello"},
            headers={"X-Learning-User": "browser-user-7"},
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "type": "reply",
        "message": "browser-user-7|solo_user|api",
        "pending_action": None,
    }
    assert state.get_current_user() == previous_user


def test_resolve_api_user_id_defaults_to_configured_local_alias(monkeypatch):
    monkeypatch.setattr(api_auth.state.config, "LOCAL_USER_ID", "shared-local-user")
    assert api_auth._resolve_api_user_id(None) == "shared-local-user"


@pytest.mark.anyio
async def test_discord_command_scope_uses_local_user_alias():
    seen = {}
    previous_user = state.get_current_user()

    async def fake_handler(ctx):
        seen["user"] = state.get_current_user()
        return "ok"

    wrapped = commands.with_ctx_user_scope(fake_handler)
    ctx = SimpleNamespace(author=SimpleNamespace(id=42))

    await wrapped(ctx)

    assert seen == {"user": state.get_local_user_id()}
    assert state.get_current_user() == previous_user


@pytest.mark.anyio
async def test_discord_on_message_uses_local_user_alias():
    seen = {}

    class _Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    message = SimpleNamespace(
        author=SimpleNamespace(id=events.config.AUTHORIZED_USER_ID, bot=False, __str__=lambda self: "Richarcl"),
        content="my answer",
        reference=None,
        channel=SimpleNamespace(typing=lambda: _Typing()),
        reply=AsyncMock(),
        add_reaction=AsyncMock(),
    )

    async def fake_handle_user_message(text, author, *, user_id=None):
        seen["text"] = text
        seen["author"] = author
        seen["user_id"] = user_id
        seen["scoped_user"] = state.get_current_user()
        return "done", None, None, None

    with (
        patch("bot.events.bot.process_commands", new=AsyncMock()),
        patch("bot.events._handle_user_message", new=AsyncMock(side_effect=fake_handle_user_message)),
        patch("bot.events.send_long_with_view", new=AsyncMock()),
    ):
        await events.on_message(message)

    assert seen == {
        "text": "my answer",
        "author": str(message.author),
        "user_id": state.get_local_user_id(),
        "scoped_user": state.get_local_user_id(),
    }


@pytest.mark.anyio
async def test_discord_reply_confirm_delegates_to_shared_resolver():
    class _Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original = SimpleNamespace(content="Pending concept", edit=AsyncMock())
    message = SimpleNamespace(
        author=SimpleNamespace(id=events.config.AUTHORIZED_USER_ID, bot=False),
        content="yes",
        reference=SimpleNamespace(message_id=321),
        channel=SimpleNamespace(fetch_message=AsyncMock(return_value=original), typing=lambda: _Typing()),
        reply=AsyncMock(),
        add_reaction=AsyncMock(),
    )
    view = views.AddConceptConfirmView({"action": "add_concept", "params": {"title": "GIL"}})
    events._pending_confirmations.clear()
    events._pending_confirmations[321] = (view.action_data, view)

    with (
        patch("bot.events.bot.process_commands", new=AsyncMock()),
        patch("bot.events.resolve_lightweight_confirmation", new=AsyncMock(return_value="✅ Added")) as resolver,
        patch("bot.events._handle_user_message", new=AsyncMock()),
    ):
        await events.on_message(message)

    resolver.assert_awaited_once_with(
        view.action_data,
        approve=True,
        user_id=state.get_local_user_id(),
    )
    original.edit.assert_awaited_once()
    assert original.edit.await_args.kwargs["view"] is view
    assert original.edit.await_args.kwargs["content"].endswith("✅ Added")
    message.add_reaction.assert_awaited_once_with("✅")
    assert view.decided is True
    assert 321 not in events._pending_confirmations


@pytest.mark.anyio
async def test_discord_reply_decline_delegates_to_shared_resolver():
    class _Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original = SimpleNamespace(content="Pending topic", edit=AsyncMock())
    message = SimpleNamespace(
        author=SimpleNamespace(id=events.config.AUTHORIZED_USER_ID, bot=False),
        content="no",
        reference=SimpleNamespace(message_id=654),
        channel=SimpleNamespace(fetch_message=AsyncMock(return_value=original), typing=lambda: _Typing()),
        reply=AsyncMock(),
        add_reaction=AsyncMock(),
    )
    view = views.SuggestTopicConfirmView({"action": "suggest_topic", "params": {"title": "ML"}})
    events._pending_confirmations.clear()
    events._pending_confirmations[654] = (view.action_data, view)

    with (
        patch("bot.events.bot.process_commands", new=AsyncMock()),
        patch("bot.events.resolve_lightweight_confirmation", new=AsyncMock(return_value=None)) as resolver,
        patch("bot.events._handle_user_message", new=AsyncMock()),
    ):
        await events.on_message(message)

    resolver.assert_awaited_once_with(
        view.action_data,
        approve=False,
        user_id=state.get_local_user_id(),
    )
    original.edit.assert_awaited_once_with(view=view)
    message.add_reaction.assert_awaited_once_with("👍")
    assert view.decided is True
    assert 654 not in events._pending_confirmations


@pytest.mark.anyio
async def test_discord_preference_command_uses_shared_pending_confirm():
    class _Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    author = SimpleNamespace(__str__=lambda self: "test-author")
    ctx = SimpleNamespace(
        interaction=None,
        channel=SimpleNamespace(typing=lambda: _Typing()),
        author=author,
        send=AsyncMock(),
    )
    pending_action = {
        "action": "preference_update",
        "message": "Proposed preference update",
        "params": {"content": "- Keep replies short."},
    }
    payload = {
        "type": "pending_confirm",
        "message": "Proposed preference update",
        "pending_action": pending_action,
    }

    with patch("bot.commands.chat_session.handle_chat_message", new=AsyncMock(return_value=payload)) as handle_mock:
        await commands.preference_command.callback(ctx, text="keep replies short")

    handle_mock.assert_awaited_once_with(
        "/preference keep replies short",
        author=str(author),
        source="discord",
    )
    ctx.send.assert_awaited_once()
    assert ctx.send.await_args.kwargs["content"] == "Proposed preference update"
    view = ctx.send.await_args.kwargs["view"]
    assert isinstance(view, views.PreferenceUpdateView)
    assert view.action_data == pending_action


@pytest.mark.anyio
async def test_preference_view_apply_and_reject_delegate_to_shared_chat_confirm():
    class _Response:
        def __init__(self):
            self.edit_message = AsyncMock()

    interaction = SimpleNamespace(
        user=SimpleNamespace(id=42),
        response=_Response(),
    )
    action_data = {
        "action": "preference_update",
        "message": "Proposed preference update",
        "params": {"content": "- Keep replies short."},
    }

    apply_view = views.PreferenceUpdateView(action_data)
    apply_button = next(child for child in apply_view.children if getattr(child, "label", None) == "Apply")
    with patch("services.views.confirm_chat_action", new=AsyncMock(return_value={"message": "Preferences updated."})) as confirm_mock:
        await apply_button.callback(interaction)

    confirm_mock.assert_awaited_once_with(action_data, source="discord")
    interaction.response.edit_message.assert_awaited_once_with(
        content="Preferences updated.",
        view=apply_view,
    )

    interaction.response.edit_message.reset_mock()
    reject_view = views.PreferenceUpdateView(action_data)
    reject_button = next(child for child in reject_view.children if getattr(child, "label", None) == "Reject")
    with patch("services.views.decline_chat_action", new=AsyncMock(return_value={"message": "Declined."})) as decline_mock:
        await reject_button.callback(interaction)

    decline_mock.assert_awaited_once_with(action_data, source="discord")
    interaction.response.edit_message.assert_awaited_once_with(
        content="Declined.",
        view=reject_view,
    )


def test_discord_interaction_views_use_local_user_alias():
    interaction = SimpleNamespace(user=SimpleNamespace(id=42))
    assert views._interaction_user_id(interaction) == state.get_local_user_id()


@pytest.mark.anyio
async def test_chat_action_skip_uses_current_scoped_user(test_db):
    captured = {}

    def fake_skip_action(concept_id, *, user_id, source):
        captured["concept_id"] = concept_id
        captured["user_id"] = user_id
        captured["source"] = source
        return {
            "message": "⏭️ Skipped — score: 10→20, next review in 3d",
            "concept_id": concept_id,
            "quality": 5,
            "actions": [{"type": "button_group", "buttons": []}],
        }

    with (
        state.current_user_scope("browser-user-7"),
        patch("services.chat_session.execute_skip_quiz_action", side_effect=fake_skip_action),
    ):
        payload = await chat_session.handle_chat_action(
            {"kind": "skip_quiz", "concept_id": 12},
            author="solo_user",
            source="api",
        )

    assert captured == {"concept_id": 12, "user_id": "browser-user-7", "source": "api"}
    assert payload["type"] == "reply"
    assert payload["message"].startswith("⏭️ Skipped — score:")
