"""
Tests for assess-driven concept relationship creation.

Verifies that _handle_assess correctly processes the optional
related_concept_ids parameter and creates relationships via db.relations.
"""

import db
from services.tools import _handle_assess

# ============================================================================
# Helpers
# ============================================================================


def _make_concept(title, topic_title="TestTopic"):
    """Create a concept under a new topic, return concept ID."""
    tid = db.add_topic(topic_title)
    cid = db.add_concept(title, "desc", [tid])
    return cid


def _base_assess_params(concept_id, quality=4, **overrides):
    """Return minimal valid assess params."""
    params = {
        "concept_id": concept_id,
        "quality": quality,
        "question_difficulty": 30,
        "assessment": "Good",
        "question_asked": "Test Q?",
        "user_response": "Test A",
        "remark": "test remark",
        "message": "Well done!",
    }
    params.update(overrides)
    return params


# ============================================================================
# Tests
# ============================================================================


class TestAssessWithoutRelations:
    """Existing assess behavior should be completely unchanged."""

    def test_basic_assess(self, test_db):
        cid = _make_concept("Basic Concept")
        params = _base_assess_params(cid)
        result_type, msg = _handle_assess(params)
        assert result_type == "reply"
        assert "Well done!" in msg

    def test_no_related_ids_key(self, test_db):
        """When related_concept_ids is not in params, no error."""
        cid = _make_concept("Concept A")
        params = _base_assess_params(cid)
        # Explicitly no related_concept_ids key
        assert "related_concept_ids" not in params
        result_type, _ = _handle_assess(params)
        assert result_type == "reply"
        assert db.get_relations(cid) == []

    def test_empty_related_ids(self, test_db):
        cid = _make_concept("Concept A")
        params = _base_assess_params(cid, related_concept_ids=[])
        result_type, _ = _handle_assess(params)
        assert result_type == "reply"
        assert db.get_relations(cid) == []


class TestAssessWithRelations:
    def test_creates_relations(self, test_db):
        c1 = _make_concept("Main Concept")
        c2 = _make_concept("Related Concept")
        params = _base_assess_params(c1, related_concept_ids=[c2])
        _handle_assess(params)

        rels = db.get_relations(c1)
        assert len(rels) == 1
        assert rels[0]["other_concept_id"] == c2
        assert rels[0]["relation_type"] == "builds_on"  # default

    def test_custom_relation_type(self, test_db):
        c1 = _make_concept("Concept A")
        c2 = _make_concept("Concept B")
        params = _base_assess_params(
            c1, related_concept_ids=[c2], relation_type="commonly_confused"
        )
        _handle_assess(params)

        rels = db.get_relations(c1)
        assert rels[0]["relation_type"] == "commonly_confused"

    def test_invalid_relation_type_defaults(self, test_db):
        c1 = _make_concept("Concept A")
        c2 = _make_concept("Concept B")
        params = _base_assess_params(c1, related_concept_ids=[c2], relation_type="invalid_type")
        _handle_assess(params)

        rels = db.get_relations(c1)
        assert len(rels) == 1
        assert rels[0]["relation_type"] == "builds_on"  # fallback

    def test_multiple_related_ids(self, test_db):
        c1 = _make_concept("Main")
        c2 = _make_concept("Rel1")
        c3 = _make_concept("Rel2")
        params = _base_assess_params(c1, related_concept_ids=[c2, c3])
        _handle_assess(params)

        rels = db.get_relations(c1)
        other_ids = {r["other_concept_id"] for r in rels}
        assert other_ids == {c2, c3}

    def test_skips_invalid_ids(self, test_db):
        c1 = _make_concept("Main")
        params = _base_assess_params(c1, related_concept_ids=[99999])
        result_type, _ = _handle_assess(params)
        assert result_type == "reply"  # no error
        assert db.get_relations(c1) == []

    def test_skips_self_reference(self, test_db):
        c1 = _make_concept("Main")
        params = _base_assess_params(c1, related_concept_ids=[c1])
        _handle_assess(params)
        assert db.get_relations(c1) == []

    def test_assess_still_updates_score(self, test_db):
        """Relationship creation shouldn't interfere with score update."""
        c1 = _make_concept("Main")
        c2 = _make_concept("Related")
        params = _base_assess_params(c1, quality=5, related_concept_ids=[c2])
        _handle_assess(params)

        concept = db.get_concept(c1)
        assert concept["mastery_level"] > 0  # score was updated
        assert concept["review_count"] == 1
