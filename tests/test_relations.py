"""
Tests for db.relations — concept-to-concept relationship CRUD.
"""

import pytest

import db
from db.relations import (
    MAX_RELATIONS_PER_CONCEPT,
    VALID_RELATION_TYPES,
    _normalize_pair,
    add_relation,
    add_relations_from_assess,
    get_all_relations,
    get_relations,
    remove_relation,
    search_related,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_topic(title="Test Topic"):
    """Create a topic and return its ID."""
    return db.add_topic(title)


def _make_concept(title, topic_id=None):
    """Create a concept under a topic and return its ID."""
    if topic_id is None:
        topic_id = _make_topic()
    return db.add_concept(title, "desc", [topic_id])


# ============================================================================
# Normalization
# ============================================================================


class TestNormalization:
    def test_normalize_pair_orders_correctly(self):
        assert _normalize_pair(5, 3) == (3, 5)
        assert _normalize_pair(1, 10) == (1, 10)

    def test_normalize_pair_rejects_self(self):
        with pytest.raises(ValueError, match="self-referential"):
            _normalize_pair(7, 7)


# ============================================================================
# CRUD
# ============================================================================


class TestAddRelation:
    def test_basic_add(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Concept A", tid)
        c2 = _make_concept("Concept B", tid)

        rel_id = add_relation(c1, c2, "builds_on")
        assert rel_id is not None
        assert isinstance(rel_id, int)

    def test_normalized_direction(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Concept A", tid)
        c2 = _make_concept("Concept B", tid)

        # Add with larger ID first — should still work
        rel_id = add_relation(c2, c1, "contrasts_with")
        assert rel_id is not None

        # Verify it's stored as (low, high)
        rels = get_relations(c1)
        assert len(rels) == 1
        assert rels[0]["relation_type"] == "contrasts_with"

    def test_duplicate_rejected(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Concept A", tid)
        c2 = _make_concept("Concept B", tid)

        rel1 = add_relation(c1, c2, "builds_on")
        rel2 = add_relation(c1, c2, "contrasts_with")  # same pair, different type
        assert rel1 is not None
        assert rel2 is None  # UNIQUE(low, high) — one edge per pair

    def test_self_relation_rejected(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Concept A", tid)
        assert add_relation(c1, c1, "builds_on") is None

    def test_invalid_type_rejected(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Concept A", tid)
        c2 = _make_concept("Concept B", tid)
        assert add_relation(c1, c2, "invalid_type") is None

    def test_all_valid_types(self, test_db):
        tid = _make_topic()
        concepts = [_make_concept(f"C{i}", tid) for i in range(len(VALID_RELATION_TYPES) + 1)]
        for i, rtype in enumerate(VALID_RELATION_TYPES):
            rel_id = add_relation(concepts[0], concepts[i + 1], rtype)
            assert rel_id is not None, f"Failed to add relation of type '{rtype}'"

    def test_with_note(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Concept A", tid)
        c2 = _make_concept("Concept B", tid)
        add_relation(c1, c2, "same_phenomenon", note="Both involve oxidation")

        rels = get_relations(c1)
        assert rels[0]["note"] == "Both involve oxidation"


class TestCapEnforcement:
    def test_cap_at_max(self, test_db):
        tid = _make_topic()
        center = _make_concept("Center", tid)
        others = [_make_concept(f"Other{i}", tid) for i in range(MAX_RELATIONS_PER_CONCEPT + 2)]

        # Fill to cap
        for i in range(MAX_RELATIONS_PER_CONCEPT):
            assert add_relation(center, others[i], "builds_on") is not None

        # One more should be rejected
        assert add_relation(center, others[MAX_RELATIONS_PER_CONCEPT], "builds_on") is None

    def test_cap_checked_for_both_sides(self, test_db):
        """If the OTHER concept is at cap, adding still fails."""
        tid = _make_topic()
        already_full = _make_concept("Full", tid)
        fillers = [_make_concept(f"Filler{i}", tid) for i in range(MAX_RELATIONS_PER_CONCEPT)]

        for f in fillers:
            add_relation(already_full, f, "builds_on")

        new_concept = _make_concept("New", tid)
        assert add_relation(new_concept, already_full, "builds_on") is None


class TestGetRelations:
    def test_returns_both_directions(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Alpha", tid)
        c2 = _make_concept("Beta", tid)
        add_relation(c1, c2, "contrasts_with")

        # Query from c1's perspective
        rels_from_c1 = get_relations(c1)
        assert len(rels_from_c1) == 1
        assert rels_from_c1[0]["other_concept_id"] == c2
        assert rels_from_c1[0]["other_title"] == "Beta"

        # Query from c2's perspective
        rels_from_c2 = get_relations(c2)
        assert len(rels_from_c2) == 1
        assert rels_from_c2[0]["other_concept_id"] == c1
        assert rels_from_c2[0]["other_title"] == "Alpha"

    def test_empty_when_no_relations(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Lonely", tid)
        assert get_relations(c1) == []


class TestRemoveRelation:
    def test_remove_existing(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("A", tid)
        c2 = _make_concept("B", tid)
        add_relation(c1, c2, "builds_on")

        assert remove_relation(c1, c2) is True
        assert get_relations(c1) == []

    def test_remove_reversed_order(self, test_db):
        """Removing with IDs in reverse order should still work."""
        tid = _make_topic()
        c1 = _make_concept("A", tid)
        c2 = _make_concept("B", tid)
        add_relation(c1, c2, "builds_on")

        assert remove_relation(c2, c1) is True

    def test_remove_nonexistent(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("A", tid)
        c2 = _make_concept("B", tid)
        assert remove_relation(c1, c2) is False


# ============================================================================
# Cascade on concept deletion
# ============================================================================


class TestCascade:
    def test_relations_cleaned_on_concept_delete(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("A", tid)
        c2 = _make_concept("B", tid)
        c3 = _make_concept("C", tid)
        add_relation(c1, c2, "builds_on")
        add_relation(c1, c3, "contrasts_with")

        db.delete_concept(c1)

        # c2 and c3 should have no relations left
        assert get_relations(c2) == []
        assert get_relations(c3) == []
        assert get_all_relations() == []


# ============================================================================
# Batch add from assess
# ============================================================================


class TestAddRelationsFromAssess:
    def test_basic_batch(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Main", tid)
        c2 = _make_concept("Related1", tid)
        c3 = _make_concept("Related2", tid)

        count = add_relations_from_assess(c1, [c2, c3])
        assert count == 2
        assert len(get_relations(c1)) == 2

    def test_skips_self(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Main", tid)
        count = add_relations_from_assess(c1, [c1])
        assert count == 0

    def test_skips_invalid_ids(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Main", tid)
        count = add_relations_from_assess(c1, [99999, "bad", None])
        assert count == 0

    def test_skips_when_capped(self, test_db):
        tid = _make_topic()
        center = _make_concept("Center", tid)
        fillers = [_make_concept(f"Fill{i}", tid) for i in range(MAX_RELATIONS_PER_CONCEPT)]
        for f in fillers:
            add_relation(center, f, "builds_on")

        extra = _make_concept("Extra", tid)
        count = add_relations_from_assess(center, [extra])
        assert count == 0

    def test_empty_list(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Main", tid)
        assert add_relations_from_assess(c1, []) == 0

    def test_invalid_type(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Main", tid)
        c2 = _make_concept("Other", tid)
        assert add_relations_from_assess(c1, [c2], relation_type="fake") == 0


# ============================================================================
# BFS search
# ============================================================================


class TestSearchRelated:
    def test_depth_1(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Start", tid)
        c2 = _make_concept("Neighbor", tid)
        c3 = _make_concept("Far", tid)
        add_relation(c1, c2, "builds_on")
        add_relation(c2, c3, "builds_on")

        results = search_related(c1, depth=1)
        ids = [r["id"] for r in results]
        assert c2 in ids
        assert c3 not in ids

    def test_depth_2(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Start", tid)
        c2 = _make_concept("Mid", tid)
        c3 = _make_concept("Far", tid)
        add_relation(c1, c2, "builds_on")
        add_relation(c2, c3, "builds_on")

        results = search_related(c1, depth=2)
        ids = [r["id"] for r in results]
        assert c2 in ids
        assert c3 in ids

    def test_excludes_start(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Start", tid)
        c2 = _make_concept("Neighbor", tid)
        add_relation(c1, c2, "builds_on")

        results = search_related(c1, depth=2)
        ids = [r["id"] for r in results]
        assert c1 not in ids

    def test_no_relations(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("Lonely", tid)
        assert search_related(c1, depth=2) == []

    def test_depth_zero(self, test_db):
        assert search_related(1, depth=0) == []


# ============================================================================
# get_all_relations
# ============================================================================


class TestGetAllRelations:
    def test_returns_all(self, test_db):
        tid = _make_topic()
        c1 = _make_concept("A", tid)
        c2 = _make_concept("B", tid)
        c3 = _make_concept("C", tid)
        add_relation(c1, c2, "builds_on")
        add_relation(c2, c3, "contrasts_with")

        all_rels = get_all_relations()
        assert len(all_rels) == 2

    def test_empty(self, test_db):
        assert get_all_relations() == []
