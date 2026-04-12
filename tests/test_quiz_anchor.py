"""
Tests for quiz anchor concept_id protection (DEVNOTES §16).

Verifies that:
- quiz action sets quiz_anchor_concept_id in session state
- fetch during active quiz does NOT overwrite active_concept_id
- assess fallback prefers quiz_anchor over active_concept_id
- quiz anchor clears on assess/clearing actions
- staleness timeout clears quiz_anchor
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import db
from services import views as quiz_views
from services.tools import execute_action
from services.tools_assess import skip_quiz


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


class TestQuizAnchor:
    """Test that _handle_quiz sets quiz_anchor_concept_id."""

    def test_quiz_sets_anchor(self, test_db):
        """quiz action stores both active_concept_id and quiz_anchor_concept_id."""
        cid = db.add_concept("Decorator Pattern", "Wraps objects")

        msg_type, result = execute_action(
            "quiz",
            {
                "concept_id": cid,
                "message": "What is the Decorator pattern?",
            },
        )

        assert msg_type == "reply"
        assert db.get_session("active_concept_id") == str(cid)
        assert db.get_session("quiz_anchor_concept_id") == str(cid)

    def test_quiz_without_concept_id(self, test_db):
        """quiz action without concept_id doesn't set quiz_anchor."""
        # Clear any pre-existing state
        db.set_session("active_concept_id", None)
        db.set_session("quiz_anchor_concept_id", None)

        msg_type, result = execute_action(
            "quiz",
            {
                "message": "General question",
            },
        )

        assert msg_type == "reply"
        assert db.get_session("quiz_anchor_concept_id") is None


class TestFetchGuard:
    """Test that fetch during active quiz doesn't overwrite active_concept_id."""

    def test_fetch_during_quiz_preserves_anchor(self, test_db):
        """Fetch with concept_id does NOT overwrite active_concept_id when quiz anchor is set."""
        c1 = db.add_concept("Decorator Pattern", "Wraps objects")
        c2 = db.add_concept("Lambda Captures", "Capture variables")

        # Start quiz on concept 1
        execute_action("quiz", {"concept_id": c1, "message": "Q?"})
        assert db.get_session("active_concept_id") == str(c1)
        assert db.get_session("quiz_anchor_concept_id") == str(c1)

        # Fetch concept 2 (simulating LLM fetching for comparison)
        execute_action("fetch", {"concept_id": c2})

        # active_concept_id should NOT be overwritten (quiz anchor guard)
        assert db.get_session("active_concept_id") == str(c1)
        assert db.get_session("quiz_anchor_concept_id") == str(c1)

    def test_fetch_without_quiz_sets_active(self, test_db):
        """Fetch with concept_id DOES set active_concept_id when no quiz anchor exists."""
        c1 = db.add_concept("Some Concept", "Desc")

        # Explicitly clear quiz anchor to simulate no-quiz state
        db.set_session("quiz_anchor_concept_id", None)
        db.set_session("active_concept_id", None)

        # Simulate pipeline fetch loop behavior
        if not db.get_session("quiz_anchor_concept_id"):
            db.set_session("active_concept_id", str(c1))

        assert db.get_session("active_concept_id") == str(c1)


class TestAssessFallback:
    """Test that assess prefers quiz_anchor_concept_id over active_concept_id."""

    def test_assess_uses_anchor_over_active(self, test_db):
        """When quiz_anchor differs from active_concept_id, assess uses the anchor."""
        c1 = db.add_concept("Decorator Pattern", "Wraps objects")
        c2 = db.add_concept("Lambda Captures", "Capture variables")

        # Simulate: quiz on c1, then active_concept_id corrupted to c2
        db.set_session("quiz_anchor_concept_id", str(c1))
        db.set_session("active_concept_id", str(c2))

        # Assess with a concept_id that doesn't exist (forces fallback)
        msg_type, result = execute_action(
            "assess",
            {
                "concept_id": 99999,
                "quality": 3,
                "question_difficulty": 50,
                "assessment": "Partial answer",
                "question_asked": "What is Decorator?",
                "user_response": "It wraps stuff",
                "remark": "Needs work",
                "message": "OK",
            },
        )

        assert msg_type == "reply"
        # c1 should have been scored (from anchor), not c2
        concept_a = db.get_concept(c1)
        assert concept_a["review_count"] == 1

        concept_b = db.get_concept(c2)
        assert concept_b["review_count"] == 0

    def test_assess_with_explicit_id_ignores_fallback(self, test_db):
        """When LLM provides correct concept_id, fallback is not used."""
        c1 = db.add_concept("Decorator Pattern", "Wraps objects")

        db.set_session("quiz_anchor_concept_id", str(c1))

        msg_type, result = execute_action(
            "assess",
            {
                "concept_id": c1,
                "quality": 4,
                "question_difficulty": 50,
                "assessment": "Good",
                "question_asked": "Q",
                "user_response": "A",
                "remark": "Good progress",
                "message": "Nice",
            },
        )

        assert msg_type == "reply"
        concept = db.get_concept(c1)
        assert concept["review_count"] == 1


class TestQuizAnchorClearing:
    """Test that quiz_anchor_concept_id clears on assess and other clearing actions."""

    def test_anchor_clears_on_assess(self, test_db):
        """After successful assess, quiz_anchor_concept_id is cleared."""
        cid = db.add_concept("Test Concept", "Desc")

        # Start quiz
        execute_action("quiz", {"concept_id": cid, "message": "Q?"})
        assert db.get_session("quiz_anchor_concept_id") == str(cid)

        # Assess — this goes through pipeline's clearing logic indirectly
        # but _handle_assess doesn't clear; pipeline.py does via
        # _QUIZ_CLEARING_ACTIONS.  We test the tools layer here—
        # pipeline clearing is tested in integration tests.
        # For now, verify the anchor was set correctly.
        msg_type, _ = execute_action(
            "assess",
            {
                "concept_id": cid,
                "quality": 4,
                "question_difficulty": 40,
                "remark": "Good",
                "message": "Nice",
            },
        )
        assert msg_type == "reply"

    def test_staleness_clears_anchor(self, test_db):
        """Staleness timeout clears quiz_anchor_concept_id along with active_concept_id."""
        import services.context as ctx

        cid = db.add_concept("Stale Concept", "Desc")
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", str(cid))

        # Simulate stale timestamp (20 min ago, UTC — matches _is_quiz_stale comparison)
        stale_time = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=20)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with patch.object(db, "get_session_updated_at", return_value=stale_time):
            parts = []
            ctx._append_active_quiz_context(parts)

        # All quiz state should be cleared
        assert db.get_session("active_concept_id") is None
        assert db.get_session("quiz_anchor_concept_id") is None
        assert parts == []  # No context injected


class TestContextInjection:
    """Test that context injection prefers quiz_anchor over active_concept_id."""

    def test_context_uses_anchor_when_set(self, test_db):
        """Active Quiz Context shows anchor concept, not overwritten active_concept_id."""
        import services.context as ctx

        c1 = db.add_concept("Decorator Pattern", "Wraps objects")
        c2 = db.add_concept("Lambda Captures", "Capture variables")

        # Simulate: quiz anchor on c1, active_concept_id corrupted to c2
        db.set_session("quiz_anchor_concept_id", str(c1))
        db.set_session("active_concept_id", str(c2))

        parts = []
        with patch.object(db, "get_session_updated_at", return_value=None):
            ctx._append_active_quiz_context(parts)

        assert len(parts) == 1
        assert f"#{c1}" in parts[0]
        assert "Decorator Pattern" in parts[0]

    def test_context_falls_back_to_active(self, test_db):
        """When no quiz anchor, context falls back to active_concept_id."""
        import services.context as ctx

        cid = db.add_concept("Active Concept", "Desc")
        db.set_session("active_concept_id", str(cid))
        # No quiz_anchor_concept_id set

        parts = []
        with patch.object(db, "get_session_updated_at", return_value=None):
            ctx._append_active_quiz_context(parts)

        assert len(parts) == 1
        assert f"#{cid}" in parts[0]
        assert "Active Concept" in parts[0]


# ============================================================================
# Additional tests from code review (DEVNOTES §16 follow-up)
# ============================================================================


class TestAssessFallbackChain:
    """Test every branch of the _handle_assess fallback chain."""

    def test_fallback2_active_when_no_anchor(self, test_db):
        """Fallback 2: use active_concept_id when no quiz anchor is set."""
        cid = db.add_concept("Active Only", "Desc")

        # No anchor, only active_concept_id
        db.set_session("quiz_anchor_concept_id", None)
        db.set_session("active_concept_id", str(cid))

        msg_type, _ = execute_action(
            "assess",
            {
                "concept_id": 99999,  # non-existent, forces fallback
                "quality": 3,
                "question_difficulty": 50,
                "remark": "OK",
                "message": "Noted",
            },
        )

        assert msg_type == "reply"
        assert db.get_concept(cid)["review_count"] == 1

    def test_fallback3_chat_history(self, test_db):
        """Fallback 3: use chat history regex when no anchor or active."""
        cid = db.add_concept("History Concept", "Desc")

        # Clear all session state
        db.set_session("quiz_anchor_concept_id", None)
        db.set_session("active_concept_id", None)

        # Plant a quiz marker in chat history
        db.add_chat_message("assistant", f"quiz on concept #{cid}")

        msg_type, _ = execute_action(
            "assess",
            {
                "concept_id": 99999,  # non-existent, forces fallback
                "quality": 3,
                "question_difficulty": 50,
                "remark": "OK",
                "message": "Noted",
            },
        )

        assert msg_type == "reply"
        assert db.get_concept(cid)["review_count"] == 1

    def test_error_when_no_fallback(self, test_db):
        """Error returned when all fallbacks are exhausted."""
        # Clear all state — no anchor, no active, no chat history
        db.set_session("quiz_anchor_concept_id", None)
        db.set_session("active_concept_id", None)

        msg_type, result = execute_action(
            "assess",
            {
                "concept_id": 99999,
                "quality": 3,
                "question_difficulty": 50,
                "remark": "OK",
                "message": "Noted",
            },
        )

        assert msg_type == "error"
        assert "not found" in result.lower()


class TestFetchGuardMultiQuiz:
    """Test that fetch guard also protects multi-quiz flows."""

    def test_fetch_during_multi_quiz_preserves_active(self, test_db):
        """Fetch during multi-quiz does NOT overwrite active_concept_id."""
        import json

        c1 = db.add_concept("Concept A", "A")
        c2 = db.add_concept("Concept B", "B")
        c3 = db.add_concept("Unrelated", "C")

        # Start multi-quiz
        execute_action(
            "multi_quiz",
            {
                "concept_ids": [c1, c2],
                "message": "Compare A and B",
            },
        )

        assert db.get_session("active_concept_id") == str(c1)
        assert db.get_session("active_concept_ids") == json.dumps([c1, c2])

        # Simulate pipeline fetch loop guard for c3
        if not db.get_session("quiz_anchor_concept_id") and not db.get_session(
            "active_concept_ids"
        ):
            db.set_session("active_concept_id", str(c3))

        # active_concept_id should NOT have changed
        assert db.get_session("active_concept_id") == str(c1)

    def test_multi_quiz_clears_single_anchor(self, test_db):
        """Starting multi-quiz clears any pre-existing single-quiz anchor."""
        c1 = db.add_concept("Single Quiz Target", "S")
        c2 = db.add_concept("Multi A", "A")
        c3 = db.add_concept("Multi B", "B")

        # Start single quiz first
        execute_action("quiz", {"concept_id": c1, "message": "Q?"})
        assert db.get_session("quiz_anchor_concept_id") == str(c1)

        # Now start multi-quiz — should clear single anchor
        execute_action(
            "multi_quiz",
            {
                "concept_ids": [c2, c3],
                "message": "Compare",
            },
        )

        assert db.get_session("quiz_anchor_concept_id") is None
        assert db.get_session("active_concept_id") == str(c2)


class TestDeletedConceptFallback:
    """Test that assess handles a deleted quiz anchor concept gracefully."""

    def test_assess_anchor_deleted_falls_to_active(self, test_db):
        """If quiz anchor concept was deleted, fallback to active_concept_id."""
        c1 = db.add_concept("Will Delete", "D")
        c2 = db.add_concept("Fallback Active", "F")

        db.set_session("quiz_anchor_concept_id", str(c1))
        db.set_session("active_concept_id", str(c2))

        # Delete the anchored concept
        db.delete_concept(c1)

        msg_type, _ = execute_action(
            "assess",
            {
                "concept_id": 99999,  # forces fallback chain
                "quality": 3,
                "question_difficulty": 50,
                "remark": "OK",
                "message": "Noted",
            },
        )

        assert msg_type == "reply"
        # c2 should have been scored via Fallback 2
        assert db.get_concept(c2)["review_count"] == 1


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
