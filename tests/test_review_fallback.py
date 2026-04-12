from unittest.mock import AsyncMock, patch

import pytest

import db
from services import chat_session, scheduler
from services.llm import LLMError


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
