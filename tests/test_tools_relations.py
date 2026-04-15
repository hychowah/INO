"""Tests for relation handlers in services.tools."""

import db


class TestRemoveRelationHandler:
    """Test the remove_relation action handler in tools.py."""

    def test_remove_existing_relation(self, test_db):
        from services.tools import execute_action

        tid = db.add_topic("Test", "")
        c1 = db.add_concept("A", "", [tid])
        c2 = db.add_concept("B", "", [tid])
        db.add_relation(c1, c2, "builds_on")
        msg_type, result = execute_action(
            "remove_relation", {"concept_id_a": c1, "concept_id_b": c2}
        )
        assert msg_type == "reply"
        assert "Removed" in result
        assert db.get_relations(c1) == []

    def test_remove_nonexistent_relation(self, test_db):
        from services.tools import execute_action

        tid = db.add_topic("Test", "")
        c1 = db.add_concept("A", "", [tid])
        c2 = db.add_concept("B", "", [tid])
        msg_type, result = execute_action(
            "remove_relation", {"concept_id_a": c1, "concept_id_b": c2}
        )
        assert msg_type == "error"
        assert "No relation" in result

    def test_remove_missing_params(self, test_db):
        from services.tools import execute_action

        msg_type, result = execute_action("remove_relation", {"concept_id_a": 1})
        assert msg_type == "error"
        assert "requires" in result
