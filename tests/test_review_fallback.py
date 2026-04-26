from unittest.mock import AsyncMock, patch

import pytest
import json

from bot import commands as bot_commands
import db
from services import chat_session, scheduler
from services.llm import LLMError


class _AsyncNullContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _MockChannel:
    def typing(self):
        return _AsyncNullContext()


class _MockCtx:
    def __init__(self):
        self.interaction = None
        self.channel = _MockChannel()
        self.author = "test-author"
        self.send = AsyncMock()
        self.typing = AsyncMock()


@pytest.mark.anyio
async def test_scheduler_fallback_uses_review_check_mode(test_db):
    cid = db.add_concept("Fallback Scheduler", "Desc")
    db.update_concept(cid, review_count=2)

    class _MockUser:
        async def send(self, _content, view=None):
            return type("Message", (), {"id": 1})()

    class _MockBot:
        def __init__(self, user):
            self._user = user

        async def fetch_user(self, _user_id):
            return self._user

    mock_send_long_with_view = AsyncMock(return_value=type("Message", (), {"id": 1})())
    fallback = AsyncMock(return_value="QUIZ")

    with (
        patch.object(scheduler, "_bot", _MockBot(_MockUser())),
        patch.object(scheduler, "_authorized_user_id", 123),
        patch("services.tools.set_action_source"),
        patch(
            "services.pipeline.generate_quiz_question",
            new=AsyncMock(side_effect=LLMError("boom", retryable=True)),
        ),
        patch("services.pipeline.call_with_fetch_loop", new=fallback),
        patch(
            "services.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: Fallback question"),
        ),
        patch("services.pipeline.process_output", return_value=("reply", "Fallback question")),
        patch("bot.messages.send_long_with_view", new=mock_send_long_with_view),
    ):
        await scheduler._send_review_quiz(f"{cid}|context")

    assert fallback.await_args.kwargs["mode"] == "review-check"


@pytest.mark.anyio
async def test_chat_review_fallback_uses_review_check_mode(test_db):
    cid = db.add_concept("Fallback Chat", "Desc")
    db.update_concept(cid, review_count=2)
    fallback = AsyncMock(return_value="QUIZ")

    with (
        patch(
            "services.chat_session.pipeline.handle_review_check", return_value=[f"{cid}|context"]
        ),
        patch("services.chat_session.set_action_source"),
        patch(
            "services.chat_session.pipeline.generate_quiz_question",
            new=AsyncMock(side_effect=LLMError("boom", retryable=True)),
        ),
        patch("services.chat_session.pipeline.call_with_fetch_loop", new=fallback),
        patch(
            "services.chat_session.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: Fallback question"),
        ),
        patch("services.chat_session.process_output", return_value=("reply", "Fallback question")),
    ):
        result = await chat_session._handle_review_command("/review")

    assert fallback.await_args.kwargs["mode"] == "review-check"
    assert result["message"] == "Fallback question"


@pytest.mark.anyio
async def test_chat_review_registers_pending_review(test_db):
    cid = db.add_concept("Review Pending", "Desc")
    db.update_concept(cid, review_count=2)

    with (
        patch(
            "services.chat_session.pipeline.handle_review_check", return_value=[f"{cid}|context"]
        ),
        patch("services.chat_session.set_action_source"),
        patch(
            "services.chat_session.pipeline.generate_quiz_question",
            new=AsyncMock(return_value={"question": "Q"}),
        ),
        patch(
            "services.chat_session.pipeline.package_quiz_for_discord",
            new=AsyncMock(return_value="QUIZ"),
        ),
        patch(
            "services.chat_session.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: Why is Fabric smoother?"),
        ),
        patch(
            "services.chat_session.process_output",
            return_value=("reply", "Why is Fabric smoother?"),
        ),
    ):
        result = await chat_session._handle_review_command("/review")

    assert result["message"] == "Why is Fabric smoother?"

    pending = json.loads(db.get_session("pending_review"))
    assert pending["concept_id"] == cid
    assert pending["question"] == "Why is Fabric smoother?"


@pytest.mark.anyio
async def test_bot_review_fallback_uses_review_check_mode(test_db):
    cid = db.add_concept("Fallback Slash", "Desc")
    db.update_concept(cid, review_count=2)
    ctx = _MockCtx()
    fallback = AsyncMock(return_value="QUIZ")

    with (
        patch("bot.commands._ensure_db"),
        patch("bot.commands.pipeline.handle_review_check", return_value=[f"{cid}|context"]),
        patch(
            "bot.commands.pipeline.generate_quiz_question",
            new=AsyncMock(side_effect=LLMError("boom", retryable=True)),
        ),
        patch("bot.commands.pipeline.call_with_fetch_loop", new=fallback),
        patch(
            "bot.commands.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: Slash fallback question"),
        ),
        patch(
            "bot.commands.pipeline.process_output",
            return_value=("reply", "Slash fallback question"),
        ),
        patch("bot.commands.send_review_question", new=AsyncMock(return_value=object())),
    ):
        await bot_commands.review_command.callback(ctx)

    assert fallback.await_args.kwargs["mode"] == "review-check"
    pending = json.loads(db.get_session("pending_review"))
    assert pending["concept_id"] == cid
    assert pending["question"] == "Slash fallback question"


@pytest.mark.anyio
async def test_bot_review_does_not_persist_pending_when_send_fails(test_db):
    cid = db.add_concept("Send Failure", "Desc")
    db.update_concept(cid, review_count=2)
    ctx = _MockCtx()

    with (
        patch("bot.commands._ensure_db"),
        patch("bot.commands.pipeline.handle_review_check", return_value=[f"{cid}|context"]),
        patch(
            "bot.commands.pipeline.generate_quiz_question",
            new=AsyncMock(return_value={"question": "Q"}),
        ),
        patch(
            "bot.commands.pipeline.package_quiz_for_discord",
            new=AsyncMock(return_value="QUIZ"),
        ),
        patch(
            "bot.commands.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: Question survives generation"),
        ),
        patch(
            "bot.commands.pipeline.process_output",
            return_value=("reply", "Question survives generation"),
        ),
        patch(
            "bot.commands.send_review_question",
            new=AsyncMock(side_effect=RuntimeError("send failed")),
        ),
    ):
        await bot_commands.review_command.callback(ctx)

    assert db.get_session("pending_review") is None
    ctx.send.assert_awaited_once()
    assert "send failed" in ctx.send.await_args.args[0]
