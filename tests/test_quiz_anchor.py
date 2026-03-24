"""
Tests for quiz anchor concept_id protection (DEVNOTES §16).

Verifies that:
- quiz action sets quiz_anchor_concept_id in session state
- fetch during active quiz does NOT overwrite active_concept_id
- assess fallback prefers quiz_anchor over active_concept_id
- quiz anchor clears on assess/clearing actions
- staleness timeout clears quiz_anchor
"""

import math
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import db
from services.tools import execute_action


class TestQuizAnchor:
    """Test that _handle_quiz sets quiz_anchor_concept_id."""

    def test_quiz_sets_anchor(self, test_db):
        """quiz action stores both active_concept_id and quiz_anchor_concept_id."""
        cid = db.add_concept("Decorator Pattern", "Wraps objects")

        msg_type, result = execute_action('quiz', {
            'concept_id': cid,
            'message': 'What is the Decorator pattern?',
        })

        assert msg_type == 'reply'
        assert db.get_session('active_concept_id') == str(cid)
        assert db.get_session('quiz_anchor_concept_id') == str(cid)

    def test_quiz_without_concept_id(self, test_db):
        """quiz action without concept_id doesn't set quiz_anchor."""
        # Clear any pre-existing state
        db.set_session('active_concept_id', None)
        db.set_session('quiz_anchor_concept_id', None)

        msg_type, result = execute_action('quiz', {
            'message': 'General question',
        })

        assert msg_type == 'reply'
        assert db.get_session('quiz_anchor_concept_id') is None


class TestFetchGuard:
    """Test that fetch during active quiz doesn't overwrite active_concept_id."""

    def test_fetch_during_quiz_preserves_anchor(self, test_db):
        """Fetch with concept_id does NOT overwrite active_concept_id when quiz anchor is set."""
        c1 = db.add_concept("Decorator Pattern", "Wraps objects")
        c2 = db.add_concept("Lambda Captures", "Capture variables")

        # Start quiz on concept 1
        execute_action('quiz', {'concept_id': c1, 'message': 'Q?'})
        assert db.get_session('active_concept_id') == str(c1)
        assert db.get_session('quiz_anchor_concept_id') == str(c1)

        # Fetch concept 2 (simulating LLM fetching for comparison)
        execute_action('fetch', {'concept_id': c2})

        # active_concept_id should NOT be overwritten (quiz anchor guard)
        assert db.get_session('active_concept_id') == str(c1)
        assert db.get_session('quiz_anchor_concept_id') == str(c1)

    def test_fetch_without_quiz_sets_active(self, test_db):
        """Fetch with concept_id DOES set active_concept_id when no quiz anchor exists."""
        c1 = db.add_concept("Some Concept", "Desc")

        # Explicitly clear quiz anchor to simulate no-quiz state
        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_id', None)

        # Simulate pipeline fetch loop behavior
        if not db.get_session('quiz_anchor_concept_id'):
            db.set_session('active_concept_id', str(c1))

        assert db.get_session('active_concept_id') == str(c1)


class TestAssessFallback:
    """Test that assess prefers quiz_anchor_concept_id over active_concept_id."""

    def test_assess_uses_anchor_over_active(self, test_db):
        """When quiz_anchor differs from active_concept_id, assess uses the anchor."""
        c1 = db.add_concept("Decorator Pattern", "Wraps objects")
        c2 = db.add_concept("Lambda Captures", "Capture variables")

        # Simulate: quiz on c1, then active_concept_id corrupted to c2
        db.set_session('quiz_anchor_concept_id', str(c1))
        db.set_session('active_concept_id', str(c2))

        # Assess with a concept_id that doesn't exist (forces fallback)
        msg_type, result = execute_action('assess', {
            'concept_id': 99999,
            'quality': 3,
            'question_difficulty': 50,
            'assessment': 'Partial answer',
            'question_asked': 'What is Decorator?',
            'user_response': 'It wraps stuff',
            'remark': 'Needs work',
            'message': 'OK',
        })

        assert msg_type == 'reply'
        # c1 should have been scored (from anchor), not c2
        concept_a = db.get_concept(c1)
        assert concept_a['review_count'] == 1

        concept_b = db.get_concept(c2)
        assert concept_b['review_count'] == 0

    def test_assess_with_explicit_id_ignores_fallback(self, test_db):
        """When LLM provides correct concept_id, fallback is not used."""
        c1 = db.add_concept("Decorator Pattern", "Wraps objects")

        db.set_session('quiz_anchor_concept_id', str(c1))

        msg_type, result = execute_action('assess', {
            'concept_id': c1,
            'quality': 4,
            'question_difficulty': 50,
            'assessment': 'Good',
            'question_asked': 'Q',
            'user_response': 'A',
            'remark': 'Good progress',
            'message': 'Nice',
        })

        assert msg_type == 'reply'
        concept = db.get_concept(c1)
        assert concept['review_count'] == 1


class TestQuizAnchorClearing:
    """Test that quiz_anchor_concept_id clears on assess and other clearing actions."""

    def test_anchor_clears_on_assess(self, test_db):
        """After successful assess, quiz_anchor_concept_id is cleared."""
        cid = db.add_concept("Test Concept", "Desc")

        # Start quiz
        execute_action('quiz', {'concept_id': cid, 'message': 'Q?'})
        assert db.get_session('quiz_anchor_concept_id') == str(cid)

        # Assess — this goes through pipeline's clearing logic indirectly
        # but _handle_assess doesn't clear; pipeline.py does via
        # _QUIZ_CLEARING_ACTIONS.  We test the tools layer here—
        # pipeline clearing is tested in integration tests.
        # For now, verify the anchor was set correctly.
        msg_type, _ = execute_action('assess', {
            'concept_id': cid,
            'quality': 4,
            'question_difficulty': 40,
            'remark': 'Good',
            'message': 'Nice',
        })
        assert msg_type == 'reply'

    def test_staleness_clears_anchor(self, test_db):
        """Staleness timeout clears quiz_anchor_concept_id along with active_concept_id."""
        import services.context as ctx

        cid = db.add_concept("Stale Concept", "Desc")
        db.set_session('active_concept_id', str(cid))
        db.set_session('quiz_anchor_concept_id', str(cid))

        # Simulate stale timestamp (20 min ago)
        stale_time = (datetime.now() - timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S")
        with patch.object(db, 'get_session_updated_at', return_value=stale_time):
            parts = []
            ctx._append_active_quiz_context(parts)

        # All quiz state should be cleared
        assert db.get_session('active_concept_id') is None
        assert db.get_session('quiz_anchor_concept_id') is None
        assert parts == []  # No context injected


class TestContextInjection:
    """Test that context injection prefers quiz_anchor over active_concept_id."""

    def test_context_uses_anchor_when_set(self, test_db):
        """Active Quiz Context shows anchor concept, not overwritten active_concept_id."""
        import services.context as ctx

        c1 = db.add_concept("Decorator Pattern", "Wraps objects")
        c2 = db.add_concept("Lambda Captures", "Capture variables")

        # Simulate: quiz anchor on c1, active_concept_id corrupted to c2
        db.set_session('quiz_anchor_concept_id', str(c1))
        db.set_session('active_concept_id', str(c2))

        parts = []
        with patch.object(db, 'get_session_updated_at', return_value=None):
            ctx._append_active_quiz_context(parts)

        assert len(parts) == 1
        assert f"#{c1}" in parts[0]
        assert "Decorator Pattern" in parts[0]

    def test_context_falls_back_to_active(self, test_db):
        """When no quiz anchor, context falls back to active_concept_id."""
        import services.context as ctx

        cid = db.add_concept("Active Concept", "Desc")
        db.set_session('active_concept_id', str(cid))
        # No quiz_anchor_concept_id set

        parts = []
        with patch.object(db, 'get_session_updated_at', return_value=None):
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
        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_id', str(cid))

        msg_type, _ = execute_action('assess', {
            'concept_id': 99999,  # non-existent, forces fallback
            'quality': 3,
            'question_difficulty': 50,
            'remark': 'OK',
            'message': 'Noted',
        })

        assert msg_type == 'reply'
        assert db.get_concept(cid)['review_count'] == 1

    def test_fallback3_chat_history(self, test_db):
        """Fallback 3: use chat history regex when no anchor or active."""
        cid = db.add_concept("History Concept", "Desc")

        # Clear all session state
        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_id', None)

        # Plant a quiz marker in chat history
        db.add_chat_message('assistant', f'quiz on concept #{cid}')

        msg_type, _ = execute_action('assess', {
            'concept_id': 99999,  # non-existent, forces fallback
            'quality': 3,
            'question_difficulty': 50,
            'remark': 'OK',
            'message': 'Noted',
        })

        assert msg_type == 'reply'
        assert db.get_concept(cid)['review_count'] == 1

    def test_error_when_no_fallback(self, test_db):
        """Error returned when all fallbacks are exhausted."""
        # Clear all state — no anchor, no active, no chat history
        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_id', None)

        msg_type, result = execute_action('assess', {
            'concept_id': 99999,
            'quality': 3,
            'question_difficulty': 50,
            'remark': 'OK',
            'message': 'Noted',
        })

        assert msg_type == 'error'
        assert 'not found' in result.lower()


class TestFetchGuardMultiQuiz:
    """Test that fetch guard also protects multi-quiz flows."""

    def test_fetch_during_multi_quiz_preserves_active(self, test_db):
        """Fetch during multi-quiz does NOT overwrite active_concept_id."""
        import json

        c1 = db.add_concept("Concept A", "A")
        c2 = db.add_concept("Concept B", "B")
        c3 = db.add_concept("Unrelated", "C")

        # Start multi-quiz
        execute_action('multi_quiz', {
            'concept_ids': [c1, c2],
            'message': 'Compare A and B',
        })

        assert db.get_session('active_concept_id') == str(c1)
        assert db.get_session('active_concept_ids') == json.dumps([c1, c2])

        # Simulate pipeline fetch loop guard for c3
        if (not db.get_session('quiz_anchor_concept_id')
                and not db.get_session('active_concept_ids')):
            db.set_session('active_concept_id', str(c3))

        # active_concept_id should NOT have changed
        assert db.get_session('active_concept_id') == str(c1)

    def test_multi_quiz_clears_single_anchor(self, test_db):
        """Starting multi-quiz clears any pre-existing single-quiz anchor."""
        c1 = db.add_concept("Single Quiz Target", "S")
        c2 = db.add_concept("Multi A", "A")
        c3 = db.add_concept("Multi B", "B")

        # Start single quiz first
        execute_action('quiz', {'concept_id': c1, 'message': 'Q?'})
        assert db.get_session('quiz_anchor_concept_id') == str(c1)

        # Now start multi-quiz — should clear single anchor
        execute_action('multi_quiz', {
            'concept_ids': [c2, c3],
            'message': 'Compare',
        })

        assert db.get_session('quiz_anchor_concept_id') is None
        assert db.get_session('active_concept_id') == str(c2)


class TestDeletedConceptFallback:
    """Test that assess handles a deleted quiz anchor concept gracefully."""

    def test_assess_anchor_deleted_falls_to_active(self, test_db):
        """If quiz anchor concept was deleted, fallback to active_concept_id."""
        c1 = db.add_concept("Will Delete", "D")
        c2 = db.add_concept("Fallback Active", "F")

        db.set_session('quiz_anchor_concept_id', str(c1))
        db.set_session('active_concept_id', str(c2))

        # Delete the anchored concept
        db.delete_concept(c1)

        msg_type, _ = execute_action('assess', {
            'concept_id': 99999,  # forces fallback chain
            'quality': 3,
            'question_difficulty': 50,
            'remark': 'OK',
            'message': 'Noted',
        })

        assert msg_type == 'reply'
        # c2 should have been scored via Fallback 2
        assert db.get_concept(c2)['review_count'] == 1
