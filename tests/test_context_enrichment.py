"""
Tests for context enrichment features:
  1. Chat history skipped for session-based providers on continuation turns
  2. Due concepts show rich relation context
  3. Active quiz context includes relations
  4. Active concept detail auto-included
  5. Pre-fetch by exact concept name
  6. Quiz generator context enriched with related concept details
  7. Shared staleness helper

Run from the learning_agent directory:
    python -m pytest tests/test_context_enrichment.py -v
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from services.context import (
    _format_relations_snippet,
    _is_quiz_stale,
    _preload_mentioned_concept,
    build_lightweight_context,
    build_prompt_context,
    build_quiz_generator_context,
)


@pytest.fixture(autouse=True)
def _temp_db(test_db):
    """Use conftest's test_db fixture + patch CHAT_DB on db.chat module too."""
    import db.chat as db_chat

    chat_path = test_db / "chat_history.db"
    original_chat_db = db_chat.CHAT_DB
    db_chat.CHAT_DB = chat_path
    # Re-init chat tables in the patched path
    db.init_databases()
    yield
    db_chat.CHAT_DB = original_chat_db


@pytest.fixture
def two_concepts():
    """Create two related concepts that are due for review."""
    from datetime import datetime

    tid = db.add_topic(title="TestTopic")
    cid1 = db.add_concept(title="Concept A", description="Desc A", topic_ids=[tid])
    cid2 = db.add_concept(title="Concept B", description="Desc B", topic_ids=[tid])
    # Make them due by setting next_review_at to the past
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    db.update_concept(cid1, next_review_at=past)
    db.update_concept(cid2, next_review_at=past)
    db.add_relation(cid1, cid2, relation_type="contrasts_with", note="A and B are often confused")
    return cid1, cid2, tid


# ============================================================================
# 1. Chat history skip for session-based providers
# ============================================================================


class TestChatHistorySkip:
    """Session-based providers should skip chat history on continuation turns."""

    def _mock_session_provider(self):
        provider = MagicMock()
        provider._sessions = {}
        return provider

    def _mock_stateless_provider(self):
        return MagicMock(spec=[])  # no _sessions attr

    def test_session_based_continuation_skips_history(self, two_concepts):
        """On continuation turn (is_new_session=False), no 'Recent Conversation' section."""
        db.add_chat_message("user", "hello")
        db.add_chat_message("assistant", "hi there")

        with patch("services.llm.get_provider", return_value=self._mock_session_provider()):
            ctx = build_lightweight_context("command", is_new_session=False)
            assert "Recent Conversation" not in ctx

    def test_session_based_new_session_includes_history(self, two_concepts):
        """On first turn (is_new_session=True), history IS included."""
        db.add_chat_message("user", "hello")
        db.add_chat_message("assistant", "hi there")

        with patch("services.llm.get_provider", return_value=self._mock_session_provider()):
            ctx = build_lightweight_context("command", is_new_session=True)
            assert "Recent Conversation" in ctx
            assert "hello" in ctx

    def test_stateless_always_includes_history(self, two_concepts):
        """Stateless providers always get chat history regardless of is_new."""
        db.add_chat_message("user", "hello")

        with patch("services.llm.get_provider", return_value=self._mock_stateless_provider()):
            ctx = build_lightweight_context("command", is_new_session=False)
            assert "Recent Conversation" in ctx


# ============================================================================
# 2. Due concepts show rich relation context
# ============================================================================


class TestDueConceptRelations:
    """Due concepts should show relation lines with scores and note snippets."""

    def test_due_concept_shows_relations(self, two_concepts):
        cid1, cid2, _ = two_concepts

        with patch("services.llm.get_provider", return_value=MagicMock(spec=[])):
            ctx = build_lightweight_context("command")
            # Should show the relation line with ↳
            assert "↳" in ctx
            assert "contrasts_with" in ctx
            assert "Concept B" in ctx

    def test_review_check_due_no_relations(self, two_concepts):
        """REVIEW-CHECK mode shows due concepts but without relations (minimal context)."""
        ctx = build_lightweight_context("REVIEW-CHECK")
        assert "Due for Review" in ctx
        # REVIEW-CHECK mode does NOT call get_relations (keeps context minimal)
        assert "↳" not in ctx


# ============================================================================
# 3. Active quiz context includes relations
# ============================================================================


class TestQuizContextRelations:
    """Active quiz context should show relations for the quizzed concept."""

    def test_single_quiz_shows_relations(self, two_concepts):
        cid1, cid2, _ = two_concepts

        with (
            patch.object(
                db,
                "get_session",
                side_effect=lambda k: {
                    "active_concept_id": str(cid1),
                    "active_concept_ids": None,
                    "quiz_anchor_concept_id": None,
                }.get(k),
            ),
            patch.object(
                db,
                "get_session_updated_at",
                return_value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
            patch("services.llm.get_provider", return_value=MagicMock(spec=[])),
        ):
            ctx = build_lightweight_context("command")
            assert "Active Quiz Context" in ctx
            assert "contrasts_with" in ctx
            assert f"#{cid2}" in ctx

    def test_multi_quiz_shows_relations(self, two_concepts):
        import json

        cid1, cid2, _ = two_concepts

        with (
            patch.object(
                db,
                "get_session",
                side_effect=lambda k: {
                    "active_concept_id": str(cid1),
                    "active_concept_ids": json.dumps([cid1, cid2]),
                    "quiz_anchor_concept_id": None,
                }.get(k),
            ),
            patch.object(
                db,
                "get_session_updated_at",
                return_value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
            patch("services.llm.get_provider", return_value=MagicMock(spec=[])),
        ):
            ctx = build_lightweight_context("command")
            assert "Active Multi-Concept Quiz" in ctx
            assert "↳" in ctx


# ============================================================================
# 4. Active concept detail auto-included
# ============================================================================


class TestActiveConceptDetail:
    """When active_concept_id is set and not stale, detail is auto-included."""

    def test_active_concept_included(self, two_concepts):
        cid1, cid2, _ = two_concepts

        with (
            patch.object(
                db,
                "get_session",
                side_effect=lambda k: {
                    "active_concept_id": str(cid1),
                    "active_concept_ids": None,
                    "quiz_anchor_concept_id": None,
                }.get(k),
            ),
            patch.object(
                db,
                "get_session_updated_at",
                return_value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
            patch("services.llm.get_provider", return_value=MagicMock(spec=[])),
        ):
            ctx = build_lightweight_context("command")
            assert "Active Concept Detail" in ctx
            assert "Concept A" in ctx

    def test_no_active_concept_no_section(self, two_concepts):
        """When no active concept_id, no detail section."""
        with patch("services.llm.get_provider", return_value=MagicMock(spec=[])):
            ctx = build_lightweight_context("command")
            assert "Active Concept Detail" not in ctx

    def test_stale_concept_not_included(self, two_concepts):
        """When quiz context is stale, active concept detail is skipped."""
        cid1, _, _ = two_concepts
        db.set_session("active_concept_id", str(cid1))

        with patch("services.context._is_quiz_stale", return_value=True):
            with patch("services.llm.get_provider", return_value=MagicMock(spec=[])):
                ctx = build_lightweight_context("command")
                assert "Active Concept Detail" not in ctx


# ============================================================================
# 5. Pre-fetch by exact concept name
# ============================================================================


class TestPreloadMentionedConcept:
    """Exact title match should pre-load concept detail."""

    def test_exact_match_preloads(self, two_concepts):
        result = _preload_mentioned_concept("Concept A")
        assert "Pre-loaded Concept" in result
        assert "Concept A" in result

    def test_case_insensitive(self, two_concepts):
        result = _preload_mentioned_concept("concept a")
        assert "Pre-loaded Concept" in result

    def test_no_match_returns_empty(self, two_concepts):
        result = _preload_mentioned_concept("Nonexistent Concept")
        assert result == ""

    def test_substring_no_match(self, two_concepts):
        """Substring/partial match should NOT trigger pre-load."""
        result = _preload_mentioned_concept("tell me about Concept A please")
        assert result == ""

    def test_empty_message_returns_empty(self):
        result = _preload_mentioned_concept("")
        assert result == ""

    def test_long_message_returns_empty(self, two_concepts):
        result = _preload_mentioned_concept("x" * 201)
        assert result == ""

    def test_preload_in_prompt_context(self, two_concepts):
        """build_prompt_context should include pre-loaded concept for exact match."""
        with patch("services.llm.get_provider", return_value=MagicMock(spec=[])):
            ctx = build_prompt_context("Concept A", mode="command")
            assert "Pre-loaded Concept" in ctx

    def test_no_preload_in_maintenance(self, two_concepts):
        """Maintenance mode should not pre-load concepts."""
        ctx = build_prompt_context("Concept A", mode="maintenance")
        assert "Pre-loaded Concept" not in ctx

    def test_topic_relevance_filter_blocks_unrelated(self, two_concepts):
        """Pre-fetch is skipped when matched concept is in a different topic than active concept."""
        cid1, cid2, _ = two_concepts
        # Create a concept in a completely different topic
        other_tid = db.add_topic(title="OtherTopic")
        db.add_concept(title="Unrelated Concept", description="Desc", topic_ids=[other_tid])
        # Set active concept to cid1 (in TestTopic)
        db.set_session("active_concept_id", str(cid1))
        with patch.object(
            db,
            "get_session",
            side_effect=lambda k: {
                "active_concept_id": str(cid1),
            }.get(k),
        ):
            result = _preload_mentioned_concept("Unrelated Concept")
            assert result == ""

    def test_topic_relevance_allows_same_topic(self, two_concepts):
        """Pre-fetch is allowed when matched concept shares a topic with active concept."""
        cid1, cid2, _ = two_concepts
        # cid2 is in same topic as cid1
        with patch.object(
            db,
            "get_session",
            side_effect=lambda k: {
                "active_concept_id": str(cid1),
            }.get(k),
        ):
            result = _preload_mentioned_concept("Concept B")
            assert "Pre-loaded Concept" in result
            assert "Concept B" in result

    def test_topic_relevance_skipped_when_no_active(self, two_concepts):
        """Pre-fetch is allowed when there's no active concept in session."""
        with patch.object(db, "get_session", return_value=None):
            result = _preload_mentioned_concept("Concept A")
            assert "Pre-loaded Concept" in result


# ============================================================================
# 6. Quiz generator enriched context
# ============================================================================


class TestQuizGeneratorEnrichment:
    """Quiz generator should include description and reviews of related concepts."""

    def test_related_concept_description_included(self, two_concepts):
        cid1, cid2, _ = two_concepts
        ctx = build_quiz_generator_context(cid1)
        assert ctx is not None
        assert "Related Concepts" in ctx
        assert "Desc B" in ctx  # description of related concept

    def test_relation_note_included(self, two_concepts):
        cid1, _, _ = two_concepts
        ctx = build_quiz_generator_context(cid1)
        assert "A and B are often confused" in ctx

    def test_nonexistent_concept_returns_none(self):
        assert build_quiz_generator_context(99999) is None


# ============================================================================
# 7. Shared helpers
# ============================================================================


class TestStalenessHelper:
    """_is_quiz_stale should check staleness based on session timestamp."""

    def test_no_timestamp_not_stale(self):
        # No active_concept_id in session → get_session_updated_at returns None
        with patch.object(db, "get_session_updated_at", return_value=None):
            assert _is_quiz_stale() is False

    def test_fresh_timestamp_not_stale(self):
        fresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with patch.object(db, "get_session_updated_at", return_value=fresh_time):
            assert _is_quiz_stale() is False

    def test_old_timestamp_is_stale(self):

        db.set_session("active_concept_id", "1")
        # Simulate old timestamp by patching
        old_time = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("db.get_session_updated_at", return_value=old_time):
            assert _is_quiz_stale() is True


class TestFormatRelationsSnippet:
    """_format_relations_snippet should return formatted relation lines."""

    def test_with_relations(self, two_concepts):
        cid1, cid2, _ = two_concepts
        lines = _format_relations_snippet(cid1)
        assert len(lines) == 1  # one relation
        assert "contrasts_with" in lines[0]
        assert "Concept B" in lines[0]

    def test_without_relations(self, two_concepts):
        # Create an isolated concept
        tid = db.add_topic(title="Isolated")
        cid = db.add_concept(title="Lone Concept", topic_ids=[tid])
        lines = _format_relations_snippet(cid)
        assert lines == []

    def test_max_rels_cap(self):
        """Should respect max_rels parameter."""
        tid = db.add_topic(title="Multi")
        cids = [db.add_concept(title=f"C{i}", topic_ids=[tid]) for i in range(4)]
        for i in range(1, 4):
            db.add_relation(cids[0], cids[i], relation_type="builds_on")
        lines = _format_relations_snippet(cids[0], max_rels=2)
        assert len(lines) == 2
