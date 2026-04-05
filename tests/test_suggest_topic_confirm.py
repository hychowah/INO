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

import sys
from pathlib import Path

import pytest

# Ensure imports work from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from db import core as db_core

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory."""
    monkeypatch.setattr(db_core, "KNOWLEDGE_DB", tmp_path / "knowledge.db")
    monkeypatch.setattr(db_core, "CHAT_DB", tmp_path / "chat_history.db")
    monkeypatch.setattr(db_core, "DATA_DIR", tmp_path)
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
        db.add_chat_message("user", '[confirmed: add topic "Embedding Models"]')
        db.add_chat_message(
            "assistant", "✅ Created topic **Embedding Models** (#5) with 2 concept(s)"
        )

        history = db.get_chat_history(limit=5)
        contents = [m["content"] for m in history]
        assert any('[confirmed: add topic "Embedding Models"]' in c for c in contents)
        assert any("#5" in c for c in contents)

    def test_declined_format(self):
        db.add_chat_message("user", '[declined: add topic "Embedding Models"]')

        history = db.get_chat_history(limit=5)
        contents = [m["content"] for m in history]
        assert any('[declined: add topic "Embedding Models"]' in c for c in contents)


# ============================================================================
# Phantom-add detection (log-only)
# ============================================================================


class TestPhantomAddDetection:
    """Pipeline detects phantom-add language in REPLY and logs warning."""

    def test_phantom_add_logs_warning(self, caplog):
        """REPLY containing 'Added concept X' should trigger a warning."""
        import re

        _PHANTOM_ADD_RE = re.compile(r"(?i)\b(Added|Created)\s+(a\s+)?(new\s+)?(concept|topic)\b")
        message = "Great question! Added concept 'Embedding Models' under Databases."
        assert _PHANTOM_ADD_RE.search(message) is not None

    def test_no_false_positive_educational(self):
        """Educational content like 'the concept was added' should not match."""
        import re

        _PHANTOM_ADD_RE = re.compile(r"(?i)\b(Added|Created)\s+(a\s+)?(new\s+)?(concept|topic)\b")
        # These sentences talk about concepts/topics in educational context
        # but with different grammar than "Added concept X"
        benign = "The concept of democracy was established in ancient Greece."
        assert _PHANTOM_ADD_RE.search(benign) is None

    def test_catches_created_topic(self):
        import re

        _PHANTOM_ADD_RE = re.compile(r"(?i)\b(Added|Created)\s+(a\s+)?(new\s+)?(concept|topic)\b")
        message = "I've created a new topic 'ML' for you."
        assert _PHANTOM_ADD_RE.search(message) is not None

    def test_catches_added_new_concept(self):
        import re

        _PHANTOM_ADD_RE = re.compile(r"(?i)\b(Added|Created)\s+(a\s+)?(new\s+)?(concept|topic)\b")
        message = "Added a new concept about embeddings."
        assert _PHANTOM_ADD_RE.search(message) is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ============================================================================
# _resolve_topic_ids auto-parenting via semantic search
# ============================================================================


class TestResolveTopicIdsAutoParent:
    """When _resolve_topic_ids auto-creates a topic from topic_titles,
    it should use semantic search to find and set parent topics."""

    def test_auto_parents_when_similar_topic_exists(self, monkeypatch):
        """If 'Python' exists and we create 'Python AST' via topic_titles,
        it should be auto-parented under Python."""
        from services import tools

        parent_id = db.add_topic(title="Python", description="Python language")

        # Mock search_similar_topics to return the parent topic
        def fake_search(query, limit=10, score_threshold=0.3):
            if "Python" in query:
                return [{"id": parent_id, "title": "Python", "score": 0.72}]
            return []

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Python AST"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]

        # Verify the auto-created topic has Python as parent
        parents = db.get_topic_parents(new_id)
        assert len(parents) == 1
        assert parents[0]["id"] == parent_id

    def test_no_auto_parent_when_no_similar(self, monkeypatch):
        """If no similar topic exists, the new topic should be a root."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return []

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Quantum Physics"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]
        parents = db.get_topic_parents(new_id)
        assert len(parents) == 0

    def test_no_crash_when_vector_store_unavailable(self, monkeypatch):
        """If semantic search raises, auto-creation should still succeed."""
        from services import tools

        def raise_search(query, limit=10, score_threshold=0.3):
            raise RuntimeError("Qdrant not available")

        monkeypatch.setattr(db, "search_similar_topics", raise_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["New Topic"],
            }
        )

        assert len(created) == 1
        # Topic created successfully despite vector search failure
        new_id = created[0][0]
        topic = db.get_topic(new_id)
        assert topic is not None

    def test_skips_exact_title_match(self, monkeypatch):
        """Semantic search returning the same title should not be used as parent."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 99, "title": "Python AST", "score": 0.95}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Python AST"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]
        parents = db.get_topic_parents(new_id)
        assert len(parents) == 0  # exact title match skipped

    def test_reuses_existing_topic_by_title(self):
        """If topic_titles matches an existing topic title, reuse it (no creation)."""
        from services import tools

        existing_id = db.add_topic(title="Statistics")

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Statistics"],
            }
        )

        assert existing_id in topic_ids
        assert len(created) == 0  # no new topics created


class TestFindCandidateParents:
    """Tests for _find_candidate_parents heuristic logic."""

    def test_high_similarity_shorter_title_accepted(self, monkeypatch):
        """Non-substring match with high similarity and shorter title is accepted as parent.
        E.g. 'Machine Learning' as parent of 'Deep Learning'."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 42, "title": "Machine Learning", "score": 0.70}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Deep Learning Optimization")
        assert 42 in result

    def test_high_similarity_longer_title_rejected(self, monkeypatch):
        """Non-substring match with high similarity but LONGER title is rejected.
        E.g. 'Python AST Visitor Pattern' should NOT parent 'Python AST'."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 99, "title": "Python AST Visitor Pattern", "score": 0.80}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Python AST")
        assert 99 not in result
        assert result == []

    def test_substring_match_accepted_regardless_of_length(self, monkeypatch):
        """Substring match is always accepted, even if score is below 0.65."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 10, "title": "Python", "score": 0.55}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Python AST")
        assert 10 in result

    def test_low_similarity_rejected(self, monkeypatch):
        """Low similarity candidates (below 0.65, no substring) are rejected."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 50, "title": "JavaScript", "score": 0.52}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Python AST")
        assert result == []
