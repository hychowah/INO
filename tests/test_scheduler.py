import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

import db
from services import scheduler, state
from services.views import QuizQuestionView


class _MockUser:
    async def send(self, content, view=None):
        return type("Message", (), {"id": 1})()


class _MockBot:
    def __init__(self, user):
        self._user = user

    async def fetch_user(self, _user_id):
        return self._user


@pytest.mark.anyio
async def test_send_review_quiz_attaches_skip_button_for_eligible_concept(test_db):
    cid = db.add_concept("Eligible Review", "Desc")
    db.update_concept(cid, review_count=3)
    user = _MockUser()
    mock_send_long_with_view = AsyncMock(return_value=type("Message", (), {"id": 1})())

    with (
        patch.object(scheduler, "_bot", _MockBot(user)),
        patch.object(scheduler, "_authorized_user_id", 123),
        patch("services.tools.set_action_source"),
        patch(
            "services.pipeline.generate_quiz_question",
            new=AsyncMock(return_value={"question": "Q"}),
        ),
        patch("services.pipeline.package_quiz_for_discord", new=AsyncMock(return_value="QUIZ")),
        patch(
            "services.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: What is eligible?"),
        ),
        patch("services.pipeline.process_output", return_value=("reply", "What is eligible?")),
        patch("bot.messages.send_long_with_view", new=mock_send_long_with_view),
    ):
        await scheduler._send_review_quiz(f"{cid}|context")

    mock_send_long_with_view.assert_awaited_once()
    call = mock_send_long_with_view.await_args
    assert call.args[0] == user.send
    assert call.args[1] == (
        "📚 **Learning Review**\nWhat is eligible?\n\n"
        "📖 **Eligible Review** · Score: 0/100 · Review #4"
    )
    assert isinstance(call.kwargs["view"], QuizQuestionView)
    assert call.kwargs["view"].concept_id == cid
    assert db.get_session("last_quiz_question") == "What is eligible?"

    pending = json.loads(db.get_session("pending_review"))
    assert pending["concept_id"] == cid
    assert pending["concept_title"] == "Eligible Review"

    reminder = db.get_scheduled_review_reminder()
    assert reminder is not None
    assert reminder["concept_id"] == cid
    assert reminder["question_text"] == "What is eligible?"
    assert reminder["status"] == "pending"


@pytest.mark.anyio
async def test_send_review_quiz_omits_skip_button_for_ineligible_concept(test_db):
    cid = db.add_concept("New Review", "Desc")
    db.update_concept(cid, review_count=1)
    user = _MockUser()
    mock_send_long_with_view = AsyncMock(return_value=type("Message", (), {"id": 1})())

    with (
        patch.object(scheduler, "_bot", _MockBot(user)),
        patch.object(scheduler, "_authorized_user_id", 123),
        patch("services.tools.set_action_source"),
        patch(
            "services.pipeline.generate_quiz_question",
            new=AsyncMock(return_value={"question": "Q"}),
        ),
        patch("services.pipeline.package_quiz_for_discord", new=AsyncMock(return_value="QUIZ")),
        patch(
            "services.pipeline.execute_llm_response",
            new=AsyncMock(return_value="REPLY: What is new?"),
        ),
        patch("services.pipeline.process_output", return_value=("reply", "What is new?")),
        patch("bot.messages.send_long_with_view", new=mock_send_long_with_view),
    ):
        await scheduler._send_review_quiz(f"{cid}|context")

    mock_send_long_with_view.assert_awaited_once()
    call = mock_send_long_with_view.await_args
    assert call.args[0] == user.send
    assert call.args[1] == (
        "📚 **Learning Review**\nWhat is new?\n\n"
        "📖 **New Review** · Score: 0/100 · Review #2\n_(skip unlocks after 1 more review(s))_"
    )
    assert call.kwargs["view"] is None


@pytest.mark.anyio
async def test_check_reviews_skips_when_pipeline_lock_is_busy(test_db):
    original_last_activity = state.last_activity_at
    state.last_activity_at = None
    state.PIPELINE_LOCK.acquire()

    try:
        with patch("services.scheduler.pipeline.handle_review_check") as mock_handle:
            await scheduler._check_reviews()
        mock_handle.assert_not_called()
    finally:
        if state.PIPELINE_LOCK.locked():
            state.PIPELINE_LOCK.release()
        state.last_activity_at = original_last_activity


@pytest.mark.anyio
async def test_check_reviews_skips_when_recent_activity_heartbeat_present(test_db):
    del test_db
    original_last_activity = state.last_activity_at
    state.last_activity_at = None
    db.set_session(state.ACTIVITY_HEARTBEAT_KEY, "1")

    try:
        with patch("services.scheduler._get_scheduled_review_payload") as payload_mock:
            await scheduler._check_reviews()
        payload_mock.assert_not_called()
    finally:
        state.last_activity_at = original_last_activity


def test_get_scheduled_review_payload_does_not_fallback_to_upcoming(test_db):
    del test_db

    with (
        patch("services.scheduler.db.get_due_concepts", return_value=[]),
        patch("services.scheduler.db.get_next_review_concept") as next_mock,
    ):
        payload = scheduler._get_scheduled_review_payload()

    assert payload is None
    next_mock.assert_not_called()


def test_is_within_review_quiet_hours_uses_utc_plus_8_window():
    assert scheduler._is_within_review_quiet_hours(datetime(2026, 4, 27, 15, 30, tzinfo=UTC))
    assert not scheduler._is_within_review_quiet_hours(datetime(2026, 4, 27, 1, 30, tzinfo=UTC))


@pytest.mark.anyio
async def test_check_reviews_clears_stale_review_in_progress_and_continues(test_db):
    del test_db
    original_last_activity = state.last_activity_at
    state.last_activity_at = None
    db.set_session("review_in_progress", "42")

    try:
        with (
            patch("services.scheduler.state.get_last_user_activity", return_value=None),
            patch(
                "services.scheduler.db.get_session_updated_at",
                side_effect=lambda key, **_: "2026-04-27 08:00:00"
                if key == "review_in_progress"
                else None,
            ),
            patch("services.scheduler._get_scheduled_review_payload", return_value=None) as payload_mock,
        ):
            await scheduler._check_reviews()

        assert db.get_session("review_in_progress") is None
        payload_mock.assert_called_once_with()
    finally:
        state.last_activity_at = original_last_activity
