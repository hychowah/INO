"""Tests for quiz-related Discord views in services.views."""

import asyncio
from unittest.mock import AsyncMock, patch

import db
from services import views as quiz_views


class _MockFollowup:
    def __init__(self):
        self.calls = []

    async def send(self, content, view=None):
        self.calls.append({"content": content, "view": view})


class _MockResponse:
    def __init__(self):
        self.calls = []

    async def edit_message(self, *, content=None, view=None):
        self.calls.append({"content": content, "view": view})


class _MockTyping:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _MockChannel:
    def typing(self):
        return _MockTyping()


class _MockInteraction:
    def __init__(self):
        self.followup = _MockFollowup()
        self.response = _MockResponse()
        self.channel = _MockChannel()
        self.user = type(
            "User",
            (),
            {
                "id": "default",
                "__str__": lambda self: "test-user",
            },
        )()
        self.message = type("Message", (), {"content": ""})()


def _get_button(view: quiz_views.QuizNavigationView, label: str):
    for child in view.children:
        if getattr(child, "label", None) == label:
            return child
    raise AssertionError(f"Button not found: {label}")


class TestQuizResponseViewDelivery:
    """Test metadata-first quiz view delivery for button flows."""

    def test_send_quiz_response_uses_quiz_meta_when_anchor_cleared(self, test_db):
        """Fresh quiz_meta reattaches the skip button even with no anchor state."""
        cid = db.add_concept("Fresh Quiz", "Desc")
        db.update_concept(cid, review_count=3)
        interaction = _MockInteraction()

        async def _send():
            await quiz_views._send_quiz_response(
                interaction,
                "Fresh quiz",
                lambda *_args: None,
                quiz_meta={"concept_id": cid, "show_skip": True},
            )

        asyncio.run(_send())

        assert len(interaction.followup.calls) == 1
        sent = interaction.followup.calls[0]
        assert sent["content"] == "Fresh quiz\n\n📖 **Fresh Quiz** · Score: 0/100 · Review #4"
        assert isinstance(sent["view"], quiz_views.QuizQuestionView)
        assert sent["view"].concept_id == cid

    def test_send_quiz_response_falls_back_to_session_anchor(self, test_db):
        """Legacy callers without quiz_meta still get the skip button from session state."""
        cid = db.add_concept("Fallback Quiz", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("quiz_anchor_concept_id", str(cid))

        interaction = _MockInteraction()

        async def _send():
            await quiz_views._send_quiz_response(
                interaction,
                "Fallback quiz",
                lambda *_args: None,
            )

        asyncio.run(_send())

        assert len(interaction.followup.calls) == 1
        sent = interaction.followup.calls[0]
        assert sent["content"] == "Fallback quiz\n\n📖 **Fallback Quiz** · Score: 0/100 · Review #4"
        assert isinstance(sent["view"], quiz_views.QuizQuestionView)
        assert sent["view"].concept_id == cid

    def test_send_quiz_response_honors_explicit_no_skip(self, test_db):
        """Explicit quiz_meta with show_skip=False sends plain text and skips fallback."""
        cid = db.add_concept("No Skip Quiz", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("quiz_anchor_concept_id", str(cid))

        interaction = _MockInteraction()

        async def _send():
            await quiz_views._send_quiz_response(
                interaction,
                "No skip quiz",
                lambda *_args: None,
                quiz_meta={"concept_id": cid, "show_skip": False},
            )

        asyncio.run(_send())

        assert len(interaction.followup.calls) == 1
        sent = interaction.followup.calls[0]
        assert sent["content"] == "No skip quiz\n\n📖 **No Skip Quiz** · Score: 0/100 · Review #4"
        assert sent["view"] is None

    def test_send_quiz_response_clears_stale_quiz_answered_for_next_skip(self, test_db):
        """Delegated follow-up quiz delivery must clear stale answered state before reattaching skip."""
        from services.tools_assess import skip_quiz

        cid = db.add_concept("Fresh Skip Quiz", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("quiz_answered", "1")
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", str(cid))
        db.set_session("last_quiz_question", "What do you remember?")

        interaction = _MockInteraction()

        async def _send():
            await quiz_views._send_quiz_response(
                interaction,
                "Fresh skip quiz",
                lambda *_args: None,
                quiz_meta={"concept_id": cid, "show_skip": True},
            )

        asyncio.run(_send())

        assert db.get_session("quiz_answered") is None
        result = skip_quiz(cid)
        assert "error" not in result


class TestQuizNavigationButtonMetadata:
    """Test that navigation buttons dispatch typed shared actions."""

    def test_quiz_again_button_dispatches_shared_action(self, test_db):
        cid = db.add_concept("Quiz Again Concept", "Desc")
        interaction = _MockInteraction()

        async def message_handler(text, author, user_id=None):
            return "unused", None, None, None

        view = quiz_views.QuizNavigationView(cid, 5, message_handler)
        button = _get_button(view, "Quiz again")

        async def _click():
            with (
                patch.object(
                    quiz_views,
                    "handle_chat_action",
                    new=AsyncMock(return_value={"message": "Fresh quiz", "actions": []}),
                ) as action_mock,
                patch("bot.messages.send_discord_result", new=AsyncMock()) as send_mock,
            ):
                await button.callback(interaction)
                action_mock.assert_awaited_once_with(
                    {"kind": "quiz_followup", "followup": "quiz_again", "concept_id": cid},
                    author="test-user",
                    source="discord",
                )
                send_mock.assert_awaited_once()

        asyncio.run(_click())

    def test_quiz_next_due_button_dispatches_shared_action(self, test_db):
        cid = db.add_concept("Next Due Concept", "Desc")
        interaction = _MockInteraction()

        async def message_handler(text, author, user_id=None):
            return "unused", None, None, None

        view = quiz_views.QuizNavigationView(cid, 5, message_handler)
        button = _get_button(view, "Next due")

        async def _click():
            with (
                patch.object(
                    quiz_views,
                    "handle_chat_action",
                    new=AsyncMock(return_value={"message": "Due quiz", "actions": []}),
                ) as action_mock,
                patch("bot.messages.send_discord_result", new=AsyncMock()) as send_mock,
            ):
                await button.callback(interaction)
                action_mock.assert_awaited_once_with(
                    {"kind": "quiz_followup", "followup": "next_due"},
                    author="test-user",
                    source="discord",
                )
                send_mock.assert_awaited_once()

        asyncio.run(_click())

    def test_quiz_explain_button_dispatches_shared_action(self, test_db):
        cid = db.add_concept("Explain Concept", "Desc")
        interaction = _MockInteraction()

        async def message_handler(text, author, user_id=None):
            return "unused", None, None, None

        view = quiz_views.QuizNavigationView(cid, 2, message_handler)
        button = _get_button(view, "Explain")

        async def _click():
            with (
                patch.object(
                    quiz_views,
                    "handle_chat_action",
                    new=AsyncMock(return_value={"message": "Explanation", "actions": []}),
                ) as action_mock,
                patch("bot.messages.send_discord_result", new=AsyncMock()) as send_mock,
            ):
                await button.callback(interaction)
                action_mock.assert_awaited_once_with(
                    {"kind": "quiz_followup", "followup": "explain", "concept_id": cid},
                    author="test-user",
                    source="discord",
                )
                send_mock.assert_awaited_once()

        asyncio.run(_click())


class TestSkipQuizButtonRegression:
    """Regression coverage for skip -> navigation -> skip-button reappearance."""

    def test_skip_then_quiz_again_reattaches_skip_button(self, test_db):
        """After skip_quiz clears the anchor, Quiz again still shows the skip button."""
        from services.tools_assess import skip_quiz

        cid = db.add_concept("Repeatable Quiz", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("quiz_answered", None)
        db.set_session("quiz_anchor_concept_id", str(cid))
        db.set_session("last_quiz_question", "What is it?")

        result = skip_quiz(cid, user_id="test-user")
        assert "error" not in result
        assert db.get_session("quiz_anchor_concept_id") is None

        interaction = _MockInteraction()

        async def message_handler(_text, _author, user_id=None):
            return (
                "Fresh quiz after skip",
                None,
                None,
                {
                    "concept_id": cid,
                    "show_skip": True,
                },
            )

        view = quiz_views.QuizNavigationView(cid, 5, message_handler)
        button = _get_button(view, "Quiz again")

        async def _click():
            await button.callback(interaction)

        asyncio.run(_click())

        assert len(interaction.followup.calls) == 1
        sent = interaction.followup.calls[0]
        assert "📖 **Repeatable Quiz** · Score:" in sent["content"]
        assert isinstance(sent["view"], quiz_views.QuizQuestionView)
        assert sent["view"].concept_id == cid
        reminder = db.get_scheduled_review_reminder()
        assert reminder is not None
        assert reminder["concept_id"] == cid
        question_text = sent["content"].split("\n\n📖", 1)[0]
        assert reminder["question_text"] == question_text

    def test_skip_button_callback_updates_session_and_navigation(self, test_db):
        """Clicking the skip button uses skip_quiz and returns navigation controls."""
        cid = db.add_concept("Callback Skip", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("quiz_answered", None)
        db.set_session("quiz_anchor_concept_id", str(cid))
        db.set_session("last_quiz_question", "What do you already know?")

        async def message_handler(_text, _author, user_id=None):
            return "unused", None, None, None

        interaction = _MockInteraction()
        view = quiz_views.QuizQuestionView(
            concept_id=cid,
            message_handler=message_handler,
            show_skip=True,
        )
        button = _get_button(view, "I know this")

        async def _click():
            await button.callback(interaction)

        asyncio.run(_click())

        assert len(interaction.response.calls) == 1
        assert interaction.response.calls[0]["view"] is view
        assert all(child.disabled for child in view.children)

        assert len(interaction.followup.calls) == 1
        sent = interaction.followup.calls[0]
        assert sent["content"].startswith("⏭️ Skipped — score:")
        assert isinstance(sent["view"], quiz_views.QuizNavigationView)
        assert sent["view"].concept_id == cid

        assert db.get_session("quiz_anchor_concept_id") is None
        assert db.get_session("quiz_answered") == "1"
        assert db.get_session("last_assess_concept_id") == str(cid)

    def test_skip_button_uses_shared_skip_executor(self, test_db):
        cid = db.add_concept("Delegated Skip", "Desc")
        db.update_concept(cid, review_count=3)

        async def message_handler(_text, _author, user_id=None):
            return "unused", None, None, None

        interaction = _MockInteraction()
        view = quiz_views.QuizQuestionView(
            concept_id=cid,
            message_handler=message_handler,
            show_skip=True,
        )
        button = _get_button(view, "I know this")

        async def _click():
            with (
                patch.object(
                    quiz_views,
                    "handle_chat_action",
                    new=AsyncMock(
                        return_value={
                            "type": "reply",
                            "message": "⏭️ Skipped — score: 10→20, next review in 3d",
                            "pending_action": None,
                            "actions": [],
                        }
                    ),
                ) as action_mock,
                patch("bot.messages.send_discord_result", new=AsyncMock()) as send_mock,
            ):
                await button.callback(interaction)
                action_mock.assert_awaited_once_with(
                    {"kind": "skip_quiz", "concept_id": cid},
                    author="test-user",
                    source="discord",
                )
                send_mock.assert_awaited_once_with(
                    interaction.followup.send,
                    "⏭️ Skipped — score: 10→20, next review in 3d",
                    message_handler,
                    actions=[],
                )

        asyncio.run(_click())

        assert interaction.followup.calls == []

    def test_skip_button_shared_action_error_uses_followup(self, test_db):
        cid = db.add_concept("Skip Error", "Desc")
        db.update_concept(cid, review_count=3)

        async def message_handler(_text, _author, user_id=None):
            return "unused", None, None, None

        interaction = _MockInteraction()
        view = quiz_views.QuizQuestionView(
            concept_id=cid,
            message_handler=message_handler,
            show_skip=True,
        )
        button = _get_button(view, "I know this")

        async def _click():
            with patch.object(
                quiz_views,
                "handle_chat_action",
                new=AsyncMock(return_value={"type": "error", "message": "blocked", "pending_action": None}),
            ) as action_mock:
                await button.callback(interaction)
                action_mock.assert_awaited_once_with(
                    {"kind": "skip_quiz", "concept_id": cid},
                    author="test-user",
                    source="discord",
                )

        asyncio.run(_click())

        assert interaction.followup.calls == [{"content": "⚠️ blocked", "view": None}]

    def test_skip_quiz_clears_stale_active_concept(self, test_db):
        """Successful skip clears active_concept_id alongside the quiz anchor."""
        from services.tools_assess import skip_quiz

        cid = db.add_concept("Skip Cleanup", "Desc")
        db.update_concept(cid, review_count=3)
        db.upsert_scheduled_review_reminder(
            cid,
            "What do you remember?",
            first_sent_at="2026-04-27 09:00:00",
            last_sent_at="2026-04-27 09:00:00",
        )
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", str(cid))
        db.set_session("last_quiz_question", "What do you remember?")

        result = skip_quiz(cid)

        assert "error" not in result
        assert db.get_session("active_concept_id") is None
        assert db.get_session("quiz_anchor_concept_id") is None
        reminder = db.get_scheduled_review_reminder(include_resolved=True)
        assert reminder is not None
        assert reminder["status"] == "skipped"

    def test_skip_quiz_blocked_when_no_active_quiz(self, test_db):
        """Stale skip callbacks are blocked once quiz anchor state is gone."""
        from services.tools_assess import skip_quiz

        cid = db.add_concept("Stale Skip", "Desc")
        db.update_concept(cid, review_count=3, mastery_level=40)
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", None)
        db.set_session("active_concept_ids", None)
        db.set_session("quiz_answered", "1")

        result = skip_quiz(cid)

        assert result == {"error": "No active quiz to skip"}
        concept = db.get_concept(cid)
        assert concept["mastery_level"] == 40
        assert concept["review_count"] == 3
