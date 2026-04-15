"""
Tests for the suggest_topic confirmation flow:
  1. execute_suggest_topic_accept creates topic + concepts in DB
  2. _handle_add_topic stashes last_added_topic_id in session
  3. Empty concepts list is handled gracefully
  4. Partial failures reported correctly
  5. Chat history entries use correct format
  6. Phantom-add detection logs warning (but not false positives)

Run from the learning_agent directory:
    python -m pytest tests/test_suggest_topic_confirm.py -v
"""

import asyncio
import logging
import sys
from pathlib import Path

import pytest

# Ensure imports work from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
import db.chat as db_chat
from db import core as db_core

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory."""
    chat_path = tmp_path / "chat_history.db"
    monkeypatch.setattr(db_core, "KNOWLEDGE_DB", tmp_path / "knowledge.db")
    monkeypatch.setattr(db_core, "CHAT_DB", chat_path)
    monkeypatch.setattr(db_core, "DATA_DIR", tmp_path)
    # db.chat imports CHAT_DB by value at import time, so patch it directly
    # so that session_state operations use the temp DB.
    monkeypatch.setattr(db_chat, "CHAT_DB", chat_path)
    db.init_databases()
    yield


# ============================================================================
# _handle_add_topic stashes last_added_topic_id
# ============================================================================


class TestAddTopicStash:
    """After _handle_add_topic, last_added_topic_id should be in session."""

    def test_stash_set_after_add_topic(self):
        from services.tools import execute_action

        msg_type, result = execute_action(
            "add_topic",
            {
                "title": "Embedding Models",
                "description": "Neural networks for text vectors",
            },
        )
        assert msg_type == "reply"
        assert "Embedding Models" in result

        stashed = db.get_session("last_added_topic_id")
        assert stashed is not None
        assert int(stashed) > 0

    def test_stash_updates_on_second_add_topic(self):
        from services.tools import execute_action

        execute_action("add_topic", {"title": "Topic A"})
        first_id = db.get_session("last_added_topic_id")

        execute_action("add_topic", {"title": "Topic B"})
        second_id = db.get_session("last_added_topic_id")

        assert first_id != second_id
        assert int(second_id) > int(first_id)


# ============================================================================
# execute_suggest_topic_accept — full flow
# ============================================================================


class TestExecuteSuggestTopicAccept:
    """Shared accept logic: creates topic + concepts in one flow."""

    def test_creates_topic_and_concepts(self):
        from services.tools import execute_suggest_topic_accept

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Embedding Models",
                "description": "Neural networks for vectors",
                "concepts": [
                    {"title": "Text Embedding Models", "description": "Words to vectors"},
                    {"title": "Cosine Similarity", "description": "Vector closeness"},
                ],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        assert topic_id is not None
        assert "Embedding Models" in summary
        assert "2 concept(s)" in summary

        # Verify in DB
        topic = db.get_topic(topic_id)
        assert topic is not None
        assert topic["title"] == "Embedding Models"

        # Verify concepts exist under the topic
        concepts = db.get_concepts_for_topic(topic_id)
        concept_titles = [c["title"] for c in concepts]
        assert "Text Embedding Models" in concept_titles
        assert "Cosine Similarity" in concept_titles

    def test_empty_concepts_list(self):
        from services.tools import execute_suggest_topic_accept

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Empty Topic",
                "description": "No concepts",
                "concepts": [],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        assert topic_id is not None
        assert "Empty Topic" in summary

        # Topic exists but has no concepts
        topic = db.get_topic(topic_id)
        assert topic is not None

    def test_no_concepts_key(self):
        from services.tools import execute_suggest_topic_accept

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Bare Topic",
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        assert topic_id is not None

    def test_partial_failure_duplicate_concept(self):
        from services.tools import execute_suggest_topic_accept

        # Pre-create a concept with the same title
        pre_tid = db.add_topic(title="Pre-existing")
        db.add_concept(title="Cosine Similarity", topic_ids=[pre_tid])

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "ML Models",
                "concepts": [
                    {"title": "Text Embeddings", "description": "New concept"},
                    {"title": "Cosine Similarity", "description": "Duplicate"},
                ],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        # Should still succeed overall (topic + at least first concept created)
        assert success is True
        assert topic_id is not None

    def test_skips_invalid_concept_entries(self):
        from services.tools import execute_suggest_topic_accept

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Mixed Concepts",
                "concepts": [
                    "plain string entry",  # not a dict, should be skipped
                    {"title": "Valid Concept", "description": "This works"},
                    {"description": "No title"},  # empty title, should be skipped
                ],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        assert topic_id is not None

    def test_creates_topic_with_parent_ids(self):
        """suggest_topic with parent_ids should create a child topic."""
        from services.tools import execute_suggest_topic_accept

        # Pre-create parent topic
        parent_id = db.add_topic(title="Python", description="Python language")

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Python AST",
                "description": "Abstract syntax tree module",
                "parent_ids": [parent_id],
                "concepts": [
                    {"title": "ast.parse()", "description": "Parse source into AST"},
                ],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        assert topic_id is not None
        assert "Python AST" in summary

        # Verify parent relationship exists
        parents = db.get_topic_parents(topic_id)
        assert len(parents) == 1
        assert parents[0]["id"] == parent_id

        # Verify concepts were created under the new child topic
        concepts = db.get_concepts_for_topic(topic_id)
        assert len(concepts) == 1
        assert concepts[0]["title"] == "ast.parse()"

    def test_creates_topic_with_parent_ids_as_int(self):
        """parent_ids as a single int (not list) should be handled."""
        from services.tools import execute_suggest_topic_accept

        parent_id = db.add_topic(title="Python")

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Python Decorators",
                "parent_ids": parent_id,  # int instead of list
                "concepts": [],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        parents = db.get_topic_parents(topic_id)
        assert len(parents) == 1
        assert parents[0]["id"] == parent_id

    def test_creates_topic_without_parent_ids(self):
        """suggest_topic without parent_ids creates a root topic (backward compat)."""
        from services.tools import execute_suggest_topic_accept

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Cooking Basics",
                "concepts": [],
            },
        }
        success, summary, topic_id = execute_suggest_topic_accept(action_data)

        assert success is True
        parents = db.get_topic_parents(topic_id)
        assert len(parents) == 0


# ============================================================================
# Chat history format for suggest_topic
# ============================================================================


class TestSuggestTopicChatHistory:
    """Verify the chat history entries match what the LLM expects."""

    def test_confirmed_format(self):
        from services.chat_actions import confirmation_history_entry
        from services.tools import execute_suggest_topic_accept

        action_data = {
            "action": "suggest_topic",
            "params": {
                "title": "Embedding Models",
                "concepts": [
                    {"title": "Sentence Embeddings", "description": "Dense vectors"},
                    {"title": "Vector Search", "description": "Nearest neighbors"},
                ],
            },
        }

        success, summary, topic_id = execute_suggest_topic_accept(action_data)
        assert success is True

        marker = confirmation_history_entry(action_data)
        db.add_chat_message("user", marker)
        db.add_chat_message("assistant", summary)

        history = db.get_chat_history(limit=5)
        contents = [m["content"] for m in history]
        assert any(marker == c for c in contents)
        assert any(f"#{topic_id}" in c for c in contents)

    def test_declined_format(self):
        from services.chat_actions import decline_history_entry

        marker = decline_history_entry(
            {
                "action": "suggest_topic",
                "params": {"title": "Embedding Models"},
            }
        )
        db.add_chat_message("user", marker)

        history = db.get_chat_history(limit=5)
        contents = [m["content"] for m in history]
        assert any(marker == c for c in contents)


# ============================================================================
# Phantom-add detection (log-only)
# ============================================================================


class TestPhantomAddDetection:
    """Pipeline detects phantom-add language in REPLY and logs warning."""

    def test_phantom_add_logs_warning(self, caplog):
        """REPLY containing 'Added concept X' should trigger the pipeline warning."""
        from services.pipeline import execute_llm_response

        message = "Great question! Added concept 'Embedding Models' under Databases."
        with caplog.at_level(logging.WARNING):
            result = asyncio.run(execute_llm_response("", f"REPLY: {message}"))

        assert result == f"REPLY: {message}"
        assert "Phantom-add detected" in caplog.text

    def test_no_false_positive_educational(self, caplog):
        """Educational content without the action pattern should not log a warning."""
        from services.pipeline import execute_llm_response

        # These sentences talk about concepts/topics in educational context
        # but with different grammar than "Added concept X"
        benign = "The concept of democracy was established in ancient Greece."
        with caplog.at_level(logging.WARNING):
            result = asyncio.run(execute_llm_response("", f"REPLY: {benign}"))

        assert result == f"REPLY: {benign}"
        assert "Phantom-add detected" not in caplog.text

    def test_catches_created_topic(self, caplog):
        from services.pipeline import execute_llm_response

        message = "I've created a new topic 'ML' for you."
        with caplog.at_level(logging.WARNING):
            asyncio.run(execute_llm_response("", f"REPLY: {message}"))

        assert "Phantom-add detected" in caplog.text

    def test_catches_added_new_concept(self, caplog):
        from services.pipeline import execute_llm_response

        message = "Added a new concept about embeddings."
        with caplog.at_level(logging.WARNING):
            asyncio.run(execute_llm_response("", f"REPLY: {message}"))

        assert "Phantom-add detected" in caplog.text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
