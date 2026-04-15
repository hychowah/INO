"""Tests for quiz-related Discord views in services.views."""

import asyncio
from unittest.mock import patch

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
        self.user = "test-user"
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


class TestQuizNavigationButtonMetadata:
    """Test that navigation buttons pass quiz_meta through to the sender helper."""

    def test_quiz_again_button_passes_quiz_meta(self, test_db):
        """Quiz again must forward fresh quiz metadata to the sender helper."""
        cid = db.add_concept("Quiz Again Concept", "Desc")
        interaction = _MockInteraction()
        captured = {}

        async def message_handler(text, author):
            captured["handler_text"] = text
            captured["handler_author"] = author
            return "Fresh quiz", None, None, {"concept_id": cid, "show_skip": True}

        async def fake_send(interaction_arg, response, message_handler_arg, *, quiz_meta=None):
            captured["interaction"] = interaction_arg
            captured["response"] = response
            captured["message_handler"] = message_handler_arg
            captured["quiz_meta"] = quiz_meta

        view = quiz_views.QuizNavigationView(cid, 5, message_handler)
        button = _get_button(view, "Quiz again")

        async def _click():
            with patch.object(quiz_views, "_send_quiz_response", new=fake_send):
                await button.callback(interaction)

        asyncio.run(_click())

        assert captured["handler_text"].startswith("[BUTTON] Quiz me again")
        assert captured["handler_author"] == "test-user"
        assert captured["interaction"] is interaction
        assert captured["response"] == "Fresh quiz"
        assert captured["message_handler"] is message_handler
        assert captured["quiz_meta"] == {"concept_id": cid, "show_skip": True}

    def test_quiz_next_due_button_passes_quiz_meta(self, test_db):
        """Next due must forward fresh quiz metadata to the sender helper."""
        cid = db.add_concept("Next Due Concept", "Desc")
        interaction = _MockInteraction()
        captured = {}

        async def message_handler(text, author):
            captured["handler_text"] = text
            captured["handler_author"] = author
            return "Due quiz", None, None, {"concept_id": cid, "show_skip": True}

        async def fake_send(interaction_arg, response, message_handler_arg, *, quiz_meta=None):
            captured["interaction"] = interaction_arg
            captured["response"] = response
            captured["message_handler"] = message_handler_arg
            captured["quiz_meta"] = quiz_meta

        view = quiz_views.QuizNavigationView(cid, 5, message_handler)
        button = _get_button(view, "Next due")

        async def _click():
            with patch.object(quiz_views, "_send_quiz_response", new=fake_send):
                await button.callback(interaction)

        asyncio.run(_click())

        assert captured["handler_text"] == "[BUTTON] Quiz me on the next due concept"
        assert captured["handler_author"] == "test-user"
        assert captured["interaction"] is interaction
        assert captured["response"] == "Due quiz"
        assert captured["message_handler"] is message_handler
        assert captured["quiz_meta"] == {"concept_id": cid, "show_skip": True}


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

        async def message_handler(_text, _author):
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
        assert sent["content"].startswith(
            "Fresh quiz after skip\n\n📖 **Repeatable Quiz** · Score:"
        )
        assert isinstance(sent["view"], quiz_views.QuizQuestionView)
        assert sent["view"].concept_id == cid

    def test_skip_button_callback_updates_session_and_navigation(self, test_db):
        """Clicking the skip button uses skip_quiz and returns navigation controls."""
        cid = db.add_concept("Callback Skip", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("quiz_answered", None)
        db.set_session("quiz_anchor_concept_id", str(cid))
        db.set_session("last_quiz_question", "What do you already know?")

        async def message_handler(_text, _author):
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

    def test_skip_quiz_clears_stale_active_concept(self, test_db):
        """Successful skip clears active_concept_id alongside the quiz anchor."""
        from services.tools_assess import skip_quiz

        cid = db.add_concept("Skip Cleanup", "Desc")
        db.update_concept(cid, review_count=3)
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", str(cid))
        db.set_session("last_quiz_question", "What do you remember?")

        result = skip_quiz(cid)

        assert "error" not in result
        assert db.get_session("active_concept_id") is None
        assert db.get_session("quiz_anchor_concept_id") is None

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
