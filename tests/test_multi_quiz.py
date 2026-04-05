"""
Tests for multi-concept quiz flow (multi_quiz, multi_assess, fetch_cluster).
"""

import json
from unittest.mock import patch

import db
from services.tools import execute_action


class TestMultiQuiz:
    """Test the multi_quiz action handler."""

    def test_multi_quiz_stores_session_state(self, test_db):
        """multi_quiz stores concept IDs in session state."""
        # Create concepts
        c1 = db.add_concept("Concept A", "Desc A")
        c2 = db.add_concept("Concept B", "Desc B")
        c3 = db.add_concept("Concept C", "Desc C")

        msg_type, result = execute_action(
            "multi_quiz",
            {
                "concept_ids": [c1, c2, c3],
                "message": "Synthesis question here",
            },
        )

        assert msg_type == "reply"
        assert "multi-concept quiz" in result

        # Check session state
        stored = db.get_session("active_concept_ids")
        assert stored is not None
        ids = json.loads(stored)
        assert set(ids) == {c1, c2, c3}

    def test_multi_quiz_requires_at_least_2(self, test_db):
        """multi_quiz rejects single concept."""
        c1 = db.add_concept("Only One", "Desc")

        msg_type, result = execute_action(
            "multi_quiz",
            {
                "concept_ids": [c1],
                "message": "question",
            },
        )

        assert msg_type == "error"
        assert "at least 2" in result

    def test_multi_quiz_filters_invalid_ids(self, test_db):
        """multi_quiz skips non-existent concept IDs."""
        c1 = db.add_concept("Real A", "Desc")
        c2 = db.add_concept("Real B", "Desc")

        msg_type, result = execute_action(
            "multi_quiz",
            {
                "concept_ids": [c1, 9999, c2],
                "message": "question",
            },
        )

        assert msg_type == "reply"
        stored = json.loads(db.get_session("active_concept_ids"))
        assert set(stored) == {c1, c2}


class TestMultiAssess:
    """Test the multi_assess action handler."""

    def test_multi_assess_scores_individually(self, test_db):
        """Each concept in multi_assess gets scored independently."""
        c1 = db.add_concept("Concept A", "Desc A")
        c2 = db.add_concept("Concept B", "Desc B")

        # Set up initial scores
        db.update_concept(c1, mastery_level=50)
        db.update_concept(c2, mastery_level=30)

        msg_type, result = execute_action(
            "multi_assess",
            {
                "assessments": [
                    {"concept_id": c1, "quality": 5, "question_difficulty": 60},
                    {"concept_id": c2, "quality": 1, "question_difficulty": 20},
                ],
                "llm_assessment": "Mixed results",
                "question_asked": "How do A and B interact?",
                "user_response": "User answer here",
            },
        )

        assert msg_type == "reply"

        # Concept A should have increased (quality 5, above level)
        a = db.get_concept(c1)
        assert a["mastery_level"] > 50

        # Concept B should have decreased (quality 1, below level)
        b = db.get_concept(c2)
        assert b["mastery_level"] < 30

    def test_multi_assess_clears_session(self, test_db):
        """multi_assess clears active_concept_ids from session."""
        c1 = db.add_concept("A", "d")
        c2 = db.add_concept("B", "d")

        db.set_session("active_concept_ids", json.dumps([c1, c2]))
        db.set_session("active_concept_id", str(c1))

        execute_action(
            "multi_assess",
            {
                "assessments": [
                    {"concept_id": c1, "quality": 3, "question_difficulty": 30},
                    {"concept_id": c2, "quality": 3, "question_difficulty": 30},
                ],
                "llm_assessment": "ok",
            },
        )

        assert db.get_session("active_concept_ids") is None
        assert db.get_session("active_concept_id") is None

    def test_multi_assess_logs_reviews(self, test_db):
        """multi_assess creates review log entries for each concept."""
        c1 = db.add_concept("A", "d")
        c2 = db.add_concept("B", "d")

        execute_action(
            "multi_assess",
            {
                "assessments": [
                    {"concept_id": c1, "quality": 4, "question_difficulty": 50},
                    {"concept_id": c2, "quality": 3, "question_difficulty": 40},
                ],
                "question_asked": "The question",
                "user_response": "The answer",
                "llm_assessment": "Good",
            },
        )

        reviews_a = db.get_recent_reviews(c1)
        reviews_b = db.get_recent_reviews(c2)
        assert len(reviews_a) == 1
        assert len(reviews_b) == 1
        assert reviews_a[0]["quality"] == 4
        assert reviews_b[0]["quality"] == 3

    def test_multi_assess_updates_scheduling(self, test_db):
        """multi_assess updates next_review_at based on new score."""
        c1 = db.add_concept("A", "d")
        db.update_concept(c1, mastery_level=50)

        execute_action(
            "multi_assess",
            {
                "assessments": [
                    {"concept_id": c1, "quality": 5, "question_difficulty": 60},
                ],
                "llm_assessment": "Great",
            },
        )

        concept = db.get_concept(c1)
        assert concept["review_count"] == 1
        assert concept["next_review_at"] is not None
        assert concept["last_reviewed_at"] is not None

    def test_multi_assess_no_penalty_above_level(self, test_db):
        """Wrong answer on hard question doesn't penalize (same as single assess)."""
        c1 = db.add_concept("A", "d")
        db.update_concept(c1, mastery_level=30)

        execute_action(
            "multi_assess",
            {
                "assessments": [
                    {"concept_id": c1, "quality": 1, "question_difficulty": 70},
                ],
                "llm_assessment": "Hard question",
            },
        )

        concept = db.get_concept(c1)
        # gap = 70 - 30 = 40 > 0, so no penalty
        assert concept["mastery_level"] == 30


class TestFetchCluster:
    """Test the fetch cluster functionality."""

    def test_fetch_cluster_returns_primary(self, test_db):
        """Fetch cluster always returns the primary concept."""
        c1 = db.add_concept("Primary Concept", "Main concept")

        msg_type, result = execute_action(
            "fetch",
            {
                "cluster": True,
                "concept_id": c1,
            },
        )

        assert msg_type == "fetch"
        assert "concept_cluster" in result
        assert result["primary_concept_id"] == c1
        assert len(result["concept_cluster"]) >= 1
        assert result["concept_cluster"][0]["id"] == c1

    def test_fetch_cluster_not_found(self, test_db):
        """Fetch cluster with missing concept returns error."""
        msg_type, result = execute_action(
            "fetch",
            {
                "cluster": True,
                "concept_id": 9999,
            },
        )

        assert msg_type == "fetch"
        assert "error" in result

    def test_fetch_cluster_uses_relations_fallback(self, test_db):
        """When no vector results, falls back to explicit relations."""
        c1 = db.add_concept("Concept A", "Desc A")
        c2 = db.add_concept("Concept B", "Desc B")

        # Create a relation between them
        db.add_relation(c1, c2, relation_type="builds_on")

        # Mock VECTORS_AVAILABLE to False
        with patch.object(db, "VECTORS_AVAILABLE", False):
            msg_type, result = execute_action(
                "fetch",
                {
                    "cluster": True,
                    "concept_id": c1,
                },
            )

        assert msg_type == "fetch"
        cluster = result["concept_cluster"]
        assert len(cluster) >= 1  # At least primary concept
