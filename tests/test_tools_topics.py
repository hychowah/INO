"""Tests for topic handlers in services.tools."""

import pytest

import db


def _make_topic(title: str):
    return db.add_topic(title)


def _make_topic_with_concepts():
    topic_id = _make_topic("Has Concepts")
    concept_id = db.add_concept("Some Concept", "desc")
    db.link_concept(concept_id, [topic_id])
    return topic_id


def _make_topic_with_children():
    parent_id = _make_topic("Parent")
    child_id = _make_topic("Child")
    db.link_topics(parent_id, child_id)
    return parent_id


class TestDeleteTopicGuard:
    """Tests for _handle_delete_topic refusing non-empty topics."""

    def test_delete_empty_topic_succeeds(self, test_db):
        from services.tools import _handle_delete_topic

        tid = _make_topic("Empty")
        result_type, _msg = _handle_delete_topic({"topic_id": tid})
        assert result_type == "reply"
        assert db.get_topic(tid) is None

    @pytest.mark.parametrize(
        ("builder", "expected_fragment"),
        [
            (_make_topic_with_concepts, "1 concept(s)"),
            (_make_topic_with_children, "1 child topic(s)"),
        ],
        ids=["concepts", "children"],
    )
    def test_delete_topic_blocked_when_not_empty(self, test_db, builder, expected_fragment):
        from services.tools import _handle_delete_topic

        topic_id = builder()

        result_type, msg = _handle_delete_topic({"topic_id": topic_id})
        assert result_type == "error"
        assert expected_fragment in msg
        assert db.get_topic(topic_id) is not None

    def test_delete_nonexistent_topic_error(self, test_db):
        from services.tools import _handle_delete_topic

        result_type, msg = _handle_delete_topic({"topic_id": 9999})
        assert result_type == "error"
        assert "not found" in msg

    def test_delete_topic_after_unlinking_concepts(self, test_db):
        from services.tools import _handle_delete_topic

        tid = _make_topic("Will Empty")
        cid = db.add_concept("Concept", "desc")
        db.link_concept(cid, [tid])

        assert _handle_delete_topic({"topic_id": tid})[0] == "error"

        db.unlink_concept(cid, tid)

        result_type, _msg = _handle_delete_topic({"topic_id": tid})
        assert result_type == "reply"
        assert db.get_topic(tid) is None
