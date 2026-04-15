"""
Tests for the add-concept confirmation flow:
  1. _handle_add_concept stashes last_added_concept_id in session state
  2. Chat history is persisted after button/text confirmation
  3. Knowledge Map uses type-prefixed IDs ([topic:N], [concept:N])

Run from the learning_agent directory:
    python -m pytest tests/test_concept_confirm.py -v
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure imports work from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
import db.chat as db_chat
from db import core as db_core
from services import views as concept_views
from services.context import build_lightweight_context


def _run(coro):
    return asyncio.run(coro)


class _MockResponse:
    def __init__(self):
        self.calls = []

    async def edit_message(self, *, content=None, view=None):
        self.calls.append({"content": content, "view": view})


class _MockInteraction:
    def __init__(self, content="Educational answer"):
        self.response = _MockResponse()
        self.message = type("Message", (), {"content": content})()


def _get_button(view: concept_views.AddConceptConfirmView, label: str):
    for child in view.children:
        if getattr(child, "label", None) == label:
            return child
    raise AssertionError(f"Button not found: {label}")


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory so tests don't touch real data."""
    chat_path = tmp_path / "chat_history.db"
    monkeypatch.setattr(db_core, "KNOWLEDGE_DB", tmp_path / "knowledge.db")
    monkeypatch.setattr(db_core, "CHAT_DB", chat_path)
    monkeypatch.setattr(db_core, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_chat, "CHAT_DB", chat_path)
    db.init_databases()
    yield


# ============================================================================
# _handle_add_concept stashes concept_id in session state
# ============================================================================


class TestAddConceptStash:
    """After _handle_add_concept, last_added_concept_id should be in session."""

    def test_stash_set_after_add_concept(self):
        from services.tools import execute_action

        # Create a topic first
        tid = db.add_topic(title="TestTopic")
        msg_type, result = execute_action(
            "add_concept",
            {
                "title": "Test Concept",
                "description": "desc",
                "topic_ids": [tid],
            },
        )
        assert msg_type == "reply"
        assert "(#" in result  # contains concept ID

        stashed = db.get_session("last_added_concept_id")
        assert stashed is not None
        assert int(stashed) > 0

    def test_stash_updates_on_second_add(self):
        from services.tools import execute_action

        tid = db.add_topic(title="TestTopic")

        execute_action(
            "add_concept",
            {
                "title": "First Concept",
                "topic_ids": [tid],
            },
        )
        first_id = db.get_session("last_added_concept_id")

        execute_action(
            "add_concept",
            {
                "title": "Second Concept",
                "topic_ids": [tid],
            },
        )
        second_id = db.get_session("last_added_concept_id")

        assert first_id != second_id
        assert int(second_id) > int(first_id)

    def test_stash_with_auto_created_topic(self):
        from services.tools import execute_action

        msg_type, result = execute_action(
            "add_concept",
            {
                "title": "GIL Concept",
                "topic_titles": ["Python"],
            },
        )
        assert msg_type == "reply"
        assert "auto-created" in result

        stashed = db.get_session("last_added_concept_id")
        assert stashed is not None
        # Verify it's actually the concept ID, not the topic ID
        concept = db.get_concept(int(stashed))
        assert concept is not None
        assert concept["title"] == "GIL Concept"


# ============================================================================
# Knowledge Map uses type-prefixed IDs
# ============================================================================


class TestKnowledgeMapPrefixes:
    """Context output should use [topic:N] and [concept:N] format."""

    def test_topic_prefix_in_knowledge_map(self):
        tid = db.add_topic(title="Stainless Steel")
        db.add_concept(title="Passivation", topic_ids=[tid])

        ctx = build_lightweight_context("command")
        assert f"[topic:{tid}]" in ctx
        # Should NOT have bare [N] format for topics
        assert f"- [{tid}]" not in ctx

    def test_concept_prefix_in_due_list(self):
        tid = db.add_topic(title="TestTopic")
        cid = db.add_concept(
            title="Due Concept",
            topic_ids=[tid],
            next_review_at="2020-01-01",  # far past → due now
        )

        ctx = build_lightweight_context("command")
        assert f"[concept:{cid}]" in ctx
        # Should NOT have bare [N] format for concepts
        lines = ctx.split("\n")
        due_lines = [ln for ln in lines if "Due Concept" in ln]
        for line in due_lines:
            assert f"[{cid}]" not in line or f"[concept:{cid}]" in line

    def test_review_check_mode_uses_concept_prefix(self):
        tid = db.add_topic(title="TestTopic")
        cid = db.add_concept(
            title="Review Concept",
            topic_ids=[tid],
            next_review_at="2020-01-01",
        )

        ctx = build_lightweight_context("REVIEW-CHECK")
        assert f"[concept:{cid}]" in ctx

    def test_no_bare_bracket_ids(self):
        """Broad check: no bare [N] ID markers that could cause confusion."""
        import re

        tid = db.add_topic(title="MyTopic")
        db.add_concept(
            title="MyConcept",
            topic_ids=[tid],
            next_review_at="2020-01-01",
        )

        ctx = build_lightweight_context("command")
        # Find all bracket patterns at line start like "- [123]" (bare numeric IDs)
        # Exclude Python list representations like "topics: [1, 2]"
        bare_ids = re.findall(r"^[\s]*-\s+\[(\d+)\]", ctx, re.MULTILINE)
        # All should be zero — every ID should be prefixed
        assert len(bare_ids) == 0, (
            f"Found bare bracket IDs {bare_ids} in context. "
            f"All IDs should be prefixed with 'topic:' or 'concept:'. "
            f"Context:\n{ctx}"
        )


# ============================================================================
# Chat history persistence after confirmation
# ============================================================================


class TestConfirmationChatHistory:
    """Use AddConceptConfirmView so history checks hit the real UI handler path."""

    def test_confirmation_saved_to_chat_history(self):
        """After button confirm, both user action and result should be in history."""
        action_data = {
            "action": "add_concept",
            "params": {
                "title": "GIL",
                "topic_titles": ["Python"],
            },
        }
        view = concept_views.AddConceptConfirmView(action_data)
        interaction = _MockInteraction()

        button = _get_button(view, "Add concept")
        _run(button.callback(interaction))

        history = db.get_chat_history(limit=5)
        assert len(history) >= 2

        contents = [m["content"] for m in history]
        stashed_id = db.get_session("last_added_concept_id")

        assert any("[confirmed: add concept]" == c for c in contents)
        assert any(f"#{stashed_id}" in c for c in contents)
        assert interaction.response.calls

    def test_decline_saved_to_chat_history(self):
        """After decline, the action should be in history."""
        view = concept_views.AddConceptConfirmView({"action": "add_concept", "params": {}})
        interaction = _MockInteraction()

        button = _get_button(view, "No thanks")
        _run(button.callback(interaction))

        history = db.get_chat_history(limit=5)
        contents = [m["content"] for m in history]
        assert any("[declined: add concept]" == c for c in contents)
        assert interaction.response.calls

    def test_concept_id_visible_in_context_after_confirm(self):
        """After confirmation, build_lightweight_context should show the concept."""
        action_data = {
            "action": "add_concept",
            "params": {
                "title": "Python GIL",
                "topic_titles": ["Python"],
            },
        }
        view = concept_views.AddConceptConfirmView(action_data)
        interaction = _MockInteraction()

        button = _get_button(view, "Add concept")
        _run(button.callback(interaction))

        # Now build context — the concept_id should appear
        ctx = build_lightweight_context("command")

        stashed_id = db.get_session("last_added_concept_id")
        assert stashed_id is not None
        # The concept ID should be visible somewhere in context
        # (either in Knowledge Map, Due list, or chat history)
        assert f"#{stashed_id}" in ctx or f"concept:{stashed_id}" in ctx


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
