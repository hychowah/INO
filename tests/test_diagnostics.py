"""Tests for Phase 6: maintenance diagnostics — relationship candidates + cluttered roots."""

from unittest.mock import patch

import db


class TestRelationshipCandidates:
    """Test FTS5-based relationship candidate discovery."""

    def test_no_candidates_with_no_concepts(self, test_db):
        diag = db.get_maintenance_diagnostics()
        assert diag["relationship_candidates"] == []

    def test_no_candidates_with_one_concept(self, test_db):
        tid = db.add_topic("Math", "")
        db.add_concept("Addition", "Adding numbers", [tid])
        diag = db.get_maintenance_diagnostics()
        assert diag["relationship_candidates"] == []

    def test_candidates_found_for_similar_titles(self, test_db):
        tid = db.add_topic("Steel", "")
        c1 = db.add_concept("Stainless Steel Grades", "Types of stainless steel", [tid])
        c2 = db.add_concept(
            "Stainless Steel Corrosion", "Corrosion resistance of stainless steel", [tid]
        )
        diag = db.get_maintenance_diagnostics()
        cands = diag["relationship_candidates"]
        # Should find a candidate pair between these two similar concepts
        assert len(cands) >= 1
        ids_in_candidates = set()
        for c in cands:
            ids_in_candidates.add(c["concept_a"]["id"])
            ids_in_candidates.add(c["concept_b"]["id"])
        assert c1 in ids_in_candidates
        assert c2 in ids_in_candidates

    def test_existing_relations_excluded(self, test_db):
        tid = db.add_topic("Steel", "")
        c1 = db.add_concept("Stainless Steel Grades", "Types of stainless steel", [tid])
        c2 = db.add_concept(
            "Stainless Steel Corrosion", "Corrosion resistance of stainless steel", [tid]
        )
        # Add a relation — should no longer appear as candidate
        db.add_relation(c1, c2, "builds_on")
        diag = db.get_maintenance_diagnostics()
        cands = diag["relationship_candidates"]
        pair_ids = {
            (
                min(c["concept_a"]["id"], c["concept_b"]["id"]),
                max(c["concept_a"]["id"], c["concept_b"]["id"]),
            )
            for c in cands
        }
        assert (min(c1, c2), max(c1, c2)) not in pair_ids

    def test_dissimilar_concepts_not_candidates(self, test_db):
        tid = db.add_topic("Mixed", "")
        db.add_concept("Quantum Entanglement", "Spooky action at distance", [tid])
        db.add_concept("Chocolate Cake Recipe", "Baking instructions", [tid])
        diag = db.get_maintenance_diagnostics()
        # Very dissimilar titles should not match
        assert diag["relationship_candidates"] == []

    def test_candidate_has_similarity_score(self, test_db):
        tid = db.add_topic("Steel", "")
        db.add_concept("Steel Welding Basics", "Intro to welding steel", [tid])
        db.add_concept("Steel Welding Techniques", "Advanced welding methods for steel", [tid])
        diag = db.get_maintenance_diagnostics()
        candidates = diag["relationship_candidates"]
        assert candidates, "expected at least one relationship candidate for similar titles"

        cand = candidates[0]
        assert "similarity" in cand
        assert 0.0 < cand["similarity"] <= 1.0

    def test_candidates_fall_back_when_vector_neighbors_are_stale(self, test_db):
        tid = db.add_topic("Steel", "")
        c1 = db.add_concept("Stainless Steel Grades", "Types of stainless steel", [tid])
        c2 = db.add_concept(
            "Stainless Steel Corrosion", "Corrosion resistance of stainless steel", [tid]
        )

        with patch(
            "db.vectors.find_nearest_concepts",
            return_value=[{"id": 999999, "title": "stale", "score": 0.95}],
        ):
            diag = db.get_maintenance_diagnostics()

        ids_in_candidates = set()
        for cand in diag["relationship_candidates"]:
            ids_in_candidates.add(cand["concept_a"]["id"])
            ids_in_candidates.add(cand["concept_b"]["id"])

        assert c1 in ids_in_candidates
        assert c2 in ids_in_candidates


class TestClutteredRootTopics:
    """Test cluttered root topics diagnostic."""

    def test_no_cluttered_when_empty(self, test_db):
        diag = db.get_maintenance_diagnostics()
        assert diag["cluttered_root_topics"] == []

    def test_no_cluttered_under_threshold(self, test_db):
        tid = db.add_topic("Small Topic", "")
        for i in range(5):
            db.add_concept(f"Concept {i}", "", [tid])
        diag = db.get_maintenance_diagnostics()
        assert diag["cluttered_root_topics"] == []

    def test_cluttered_detected_above_10(self, test_db):
        tid = db.add_topic("Big Topic", "")
        for i in range(12):
            db.add_concept(f"Concept {i}", "", [tid])
        diag = db.get_maintenance_diagnostics()
        cluttered = diag["cluttered_root_topics"]
        assert len(cluttered) == 1
        assert cluttered[0]["id"] == tid
        assert cluttered[0]["concept_count"] == 12

    def test_topic_with_subtopics_not_cluttered(self, test_db):
        parent = db.add_topic("Parent", "")
        child = db.add_topic("Child", "")
        db.link_topics(parent, child)
        for i in range(15):
            db.add_concept(f"Concept {i}", "", [parent])
        diag = db.get_maintenance_diagnostics()
        # Parent has subtopics, so not "cluttered" even with many concepts
        cluttered_ids = [t["id"] for t in diag["cluttered_root_topics"]]
        assert parent not in cluttered_ids

    def test_child_topic_not_in_cluttered_roots(self, test_db):
        parent = db.add_topic("Parent", "")
        child = db.add_topic("Child", "")
        db.link_topics(parent, child)
        for i in range(15):
            db.add_concept(f"Concept {i}", "", [child])
        diag = db.get_maintenance_diagnostics()
        # Child is not a root — should not appear
        cluttered_ids = [t["id"] for t in diag["cluttered_root_topics"]]
        assert child not in cluttered_ids


class TestEmptyTopicsDiagnostics:
    def test_topic_with_children_not_in_empty_list(self, test_db):
        """Topics with child subtopics should not appear in empty_topics."""
        parent = db.add_topic("Parent", "")
        child = db.add_topic("Child", "")
        db.link_topics(parent, child)

        diag = db.get_maintenance_diagnostics()
        empty_ids = [t["id"] for t in diag["empty_topics"]]
        assert child in empty_ids
        assert parent not in empty_ids

    def test_truly_empty_topic_in_empty_list(self, test_db):
        """Topic with no concepts and no children appears in empty_topics."""
        tid = db.add_topic("Lonely", "")
        diag = db.get_maintenance_diagnostics()
        empty_ids = [t["id"] for t in diag["empty_topics"]]
        assert tid in empty_ids
