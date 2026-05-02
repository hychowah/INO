"""Focused tests for adapter-level current-user scoping."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from api import app
from api.routes import chat as chat_routes
from bot import handler
from services import state


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
        "message": f"{chat_routes.LOCAL_API_USER_ID}|solo_user|api",
        "pending_action": None,
    }
    assert state.get_current_user() == previous_user