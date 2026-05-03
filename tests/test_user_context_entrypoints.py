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
        patch("bot.handler.pipeline.call_with_fetch_loop", new=AsyncMock(side_effect=fake_fetch_loop)),
        patch("bot.handler.parse_llm_response", return_value=("REPLY", "raw", None)),
        patch("bot.handler.pipeline.execute_llm_response", new=AsyncMock(return_value="REPLY: done")),
        patch("bot.handler.pipeline.process_output", return_value=("reply", "done")),
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


def test_discord_interaction_views_use_local_user_alias():
    interaction = SimpleNamespace(user=SimpleNamespace(id=42))
    assert views._interaction_user_id(interaction) == state.get_local_user_id()


@pytest.mark.anyio
async def test_chat_action_skip_uses_current_scoped_user(test_db):
    captured = {}

    def fake_skip_quiz(concept_id, *, user_id, source):
        captured["concept_id"] = concept_id
        captured["user_id"] = user_id
        captured["source"] = source
        return {
            "old_score": 10,
            "new_score": 20,
            "interval_days": 3,
            "concept_id": concept_id,
        }

    with (
        state.current_user_scope("browser-user-7"),
        patch("services.chat_session.skip_quiz", side_effect=fake_skip_quiz),
    ):
        payload = await chat_session.handle_chat_action(
            {"kind": "skip_quiz", "concept_id": 12},
            author="solo_user",
            source="api",
        )

    assert captured == {"concept_id": 12, "user_id": "browser-user-7", "source": "api"}
    assert payload["type"] == "reply"
    assert payload["message"].startswith("⏭️ Skipped — score:")