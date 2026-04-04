"""
Tests for the assess/multi_assess guard in pipeline.execute_action.

Verifies that:
- assess is blocked when no quiz is active (no quiz_anchor_concept_id,
  no active_concept_ids), preventing spurious score changes on follow-up
  questions after a quiz cycle completes.
- assess IS allowed when quiz_anchor_concept_id is set (quiz active).
- multi_assess is blocked when active_concept_ids is not set.
- multi_assess IS allowed when active_concept_ids is set.
- Concept scores are NOT modified when assess is blocked.
- The blocked call returns the LLM's message as a plain REPLY.
"""

import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock

import db
from services.tools import execute_action as quiz_action


# ============================================================================
# Helpers
# ============================================================================

def _run(coro):
    """Run a coroutine synchronously in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _pipeline_execute(action_data: dict) -> str:
    """Call pipeline.execute_action with repair disabled to keep tests simple."""
    from services import pipeline
    with patch('services.pipeline.repair_action', new=AsyncMock(return_value=None)):
        return await pipeline.execute_action(action_data)


# ============================================================================
# Tests: assess blocked when no quiz active
# ============================================================================

class TestAssessBlockedNoQuiz:
    """assess must not run when no quiz is active."""

    def test_assess_blocked_returns_message(self, test_db):
        """When no quiz is active, pipeline blocks assess and returns LLM message."""
        cid = db.add_concept("B-Tree Indexing", "Database index structure")
        db.update_concept(cid, mastery_level=30)

        # Ensure no quiz state
        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_ids', None)

        action_data = {
            'action': 'assess',
            'params': {
                'concept_id': cid,
                'quality': 5,
                'question_difficulty': 50,
                'assessment': 'Perfect answer',
                'question_asked': 'What is a B-tree?',
                'user_response': 'B-tree has lots of children and reduces I/O',
                'remark': 'User knows this well',
            },
            'message': "Spot on! B-trees have wide fanout. Want another question? 🧠",
        }

        result = _run(_pipeline_execute(action_data))

        # Should return the LLM message as REPLY, not an error
        assert result.startswith("REPLY: ")
        assert "Spot on!" in result

    def test_assess_blocked_no_score_change(self, test_db):
        """When blocked, concept score must NOT be modified."""
        cid = db.add_concept("B-Tree Indexing", "Database index structure")
        db.update_concept(cid, mastery_level=30)

        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_ids', None)

        action_data = {
            'action': 'assess',
            'params': {
                'concept_id': cid,
                'quality': 5,
                'question_difficulty': 50,
            },
            'message': "Great answer!",
        }

        _run(_pipeline_execute(action_data))

        # Score must remain unchanged
        concept = db.get_concept(cid)
        assert concept['mastery_level'] == 30
        assert concept['review_count'] == 0

    def test_assess_blocked_no_action_log_entry(self, test_db):
        """When blocked, no action_log entry must be created for the assess."""
        cid = db.add_concept("Binary Search Tree", "BST concept")

        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_ids', None)

        from db import action_log
        before = action_log.get_action_log(action_filter='assess')

        action_data = {
            'action': 'assess',
            'params': {'concept_id': cid, 'quality': 4, 'question_difficulty': 40},
            'message': "Good job!",
        }
        _run(_pipeline_execute(action_data))

        after = action_log.get_action_log(action_filter='assess')
        assert len(after) == len(before), "Spurious assess must not create an action_log entry"

    def test_assess_blocked_no_review_logged(self, test_db):
        """When blocked, no review entry must be added to the reviews table."""
        cid = db.add_concept("FTS5 Tokenizer", "Full-text search component")

        db.set_session('quiz_anchor_concept_id', None)
        db.set_session('active_concept_ids', None)

        action_data = {
            'action': 'assess',
            'params': {
                'concept_id': cid,
                'quality': 5,
                'question_difficulty': 60,
                'question_asked': 'What does FTS5 use internally?',
                'user_response': 'B-tree for prefix indexing',
            },
            'message': "Exactly right!",
        }
        _run(_pipeline_execute(action_data))

        reviews = db.get_recent_reviews(cid)
        assert reviews == [], "Spurious assess must not create a review entry"


# ============================================================================
# Tests: assess ALLOWED when quiz is active
# ============================================================================

class TestAssessAllowedWithQuiz:
    """assess must proceed normally when a quiz is active."""

    def test_assess_allowed_with_anchor(self, test_db):
        """assess proceeds when quiz_anchor_concept_id is set."""
        cid = db.add_concept("B+ Tree", "B-tree variant with linked leaves")
        db.update_concept(cid, mastery_level=20)

        # Simulate quiz having been sent
        quiz_action('quiz', {'concept_id': cid, 'message': 'Compare B and B+ tree'})
        assert db.get_session('quiz_anchor_concept_id') == str(cid)

        action_data = {
            'action': 'assess',
            'params': {
                'concept_id': cid,
                'quality': 4,
                'question_difficulty': 40,
                'assessment': 'Correct',
                'question_asked': 'Compare B and B+ tree',
                'user_response': 'B+ keeps data only in leaves',
                'remark': 'Knows the key difference',
            },
            'message': "Well done! B+ tree keeps all data in leaves for efficient scans.",
        }

        result = _run(_pipeline_execute(action_data))

        assert result.startswith("REPLY: ")
        # Score should have increased
        concept = db.get_concept(cid)
        assert concept['mastery_level'] > 20
        assert concept['review_count'] == 1

    def test_quiz_anchor_cleared_after_assess(self, test_db):
        """After a successful assess, quiz_anchor_concept_id is cleared."""
        cid = db.add_concept("B-Tree", "Self-balancing search tree")

        quiz_action('quiz', {'concept_id': cid, 'message': 'What is a B-tree?'})
        assert db.get_session('quiz_anchor_concept_id') == str(cid)

        action_data = {
            'action': 'assess',
            'params': {
                'concept_id': cid,
                'quality': 5,
                'question_difficulty': 30,
                'remark': 'Perfect',
            },
            'message': "Perfect!",
        }
        _run(_pipeline_execute(action_data))

        # quiz_anchor_concept_id should now be cleared
        assert db.get_session('quiz_anchor_concept_id') is None

    def test_second_assess_blocked_after_first_succeeds(self, test_db):
        """After a quiz is answered, a second assess on the same concept is blocked."""
        cid = db.add_concept("B-Tree Indexing", "Index structure")
        db.update_concept(cid, mastery_level=30)

        # Send quiz
        quiz_action('quiz', {'concept_id': cid, 'message': 'Why use B-trees?'})

        # First assess (valid — quiz is active)
        first_action = {
            'action': 'assess',
            'params': {'concept_id': cid, 'quality': 5, 'question_difficulty': 40},
            'message': "Spot on!",
        }
        _run(_pipeline_execute(first_action))
        score_after_first = db.get_concept(cid)['mastery_level']
        assert score_after_first > 30

        # Second assess (spurious — quiz anchor now cleared)
        assert db.get_session('quiz_anchor_concept_id') is None

        second_action = {
            'action': 'assess',
            'params': {'concept_id': cid, 'quality': 5, 'question_difficulty': 40},
            'message': "Also great!",
        }
        _run(_pipeline_execute(second_action))

        # Score must NOT have changed a second time
        score_after_second = db.get_concept(cid)['mastery_level']
        assert score_after_second == score_after_first, (
            "Second assess (no active quiz) must not modify the score"
        )
        assert db.get_concept(cid)['review_count'] == 1, (
            "Only one review should be recorded"
        )


# ============================================================================
# Tests: multi_assess guard
# ============================================================================

class TestMultiAssessGuard:
    """multi_assess must be blocked when no multi-quiz is active."""

    def test_multi_assess_blocked_no_active_ids(self, test_db):
        """multi_assess blocked when active_concept_ids is not set."""
        c1 = db.add_concept("B-Tree", "Balanced tree")
        c2 = db.add_concept("B+ Tree", "B-tree variant")
        db.update_concept(c1, mastery_level=40)
        db.update_concept(c2, mastery_level=40)

        db.set_session('active_concept_ids', None)
        db.set_session('quiz_anchor_concept_id', None)

        action_data = {
            'action': 'multi_assess',
            'params': {
                'assessments': [
                    {'concept_id': c1, 'quality': 5, 'question_difficulty': 50},
                    {'concept_id': c2, 'quality': 4, 'question_difficulty': 50},
                ],
                'llm_assessment': 'Great synthesis',
            },
            'message': "Excellent comparison!",
        }

        result = _run(_pipeline_execute(action_data))

        assert result.startswith("REPLY: ")
        # Scores must NOT change
        assert db.get_concept(c1)['mastery_level'] == 40
        assert db.get_concept(c2)['mastery_level'] == 40

    def test_multi_assess_allowed_with_active_ids(self, test_db):
        """multi_assess proceeds when active_concept_ids is set."""
        c1 = db.add_concept("B-Tree", "Balanced tree")
        c2 = db.add_concept("B+ Tree", "B-tree variant")
        db.update_concept(c1, mastery_level=40)
        db.update_concept(c2, mastery_level=40)

        # Simulate multi_quiz having been sent
        quiz_action('multi_quiz', {
            'concept_ids': [c1, c2],
            'message': 'Compare B-tree and B+ tree',
        })
        assert db.get_session('active_concept_ids') is not None

        action_data = {
            'action': 'multi_assess',
            'params': {
                'assessments': [
                    {'concept_id': c1, 'quality': 5, 'question_difficulty': 55},
                    {'concept_id': c2, 'quality': 4, 'question_difficulty': 55},
                ],
                'llm_assessment': 'Great synthesis answer',
                'question_asked': 'Compare B-tree and B+ tree',
                'user_response': 'B+ tree links leaves for sequential scans',
            },
            'message': "Excellent! You nailed the key difference.",
        }

        result = _run(_pipeline_execute(action_data))

        assert result.startswith("REPLY: ")
        # Scores should have increased
        assert db.get_concept(c1)['mastery_level'] > 40
        assert db.get_concept(c2)['mastery_level'] > 40
