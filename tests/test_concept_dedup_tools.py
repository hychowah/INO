"""Tests for the tool- and DB-level concept dedup guard.

Covers:
1. Exact-title duplicate reuse through the add_concept flow
2. Case-insensitive duplicate detection helpers
3. DB-level duplicate safety net behavior
4. Concept-count integrity across repeated add_concept calls

Direct services.dedup coverage lives in tests/test_dedup.py.
"""

from unittest.mock import patch

import pytest

import db
from db import core as db_core
from services.tools import _check_concept_duplicate, execute_action


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory so tests don't touch real data."""
    monkeypatch.setattr(db_core, "KNOWLEDGE_DB", tmp_path / "knowledge.db")
    monkeypatch.setattr(db_core, "CHAT_DB", tmp_path / "chat_history.db")
    monkeypatch.setattr(db_core, "DATA_DIR", tmp_path)
    db.init_databases()
    yield


class TestFindConceptByTitle:
    def test_finds_exact_match(self):
        tid = db.add_topic(title="TestTopic")
        db.add_concept(title="Chromium Oxide", topic_ids=[tid])
        result = db.find_concept_by_title("Chromium Oxide")
        assert result is not None
        assert result["title"] == "Chromium Oxide"

    def test_finds_case_insensitive(self):
        tid = db.add_topic(title="TestTopic")
        db.add_concept(title="Chromium Oxide", topic_ids=[tid])
        result = db.find_concept_by_title("chromium oxide")
        assert result is not None
        assert result["title"] == "Chromium Oxide"

    def test_returns_none_when_not_found(self):
        result = db.find_concept_by_title("Nonexistent Concept")
        assert result is None

    def test_includes_topic_ids(self):
        t1 = db.add_topic(title="Topic A")
        t2 = db.add_topic(title="Topic B")
        db.add_concept(title="Multi-Topic Concept", topic_ids=[t1, t2])
        result = db.find_concept_by_title("Multi-Topic Concept")
        assert result is not None
        assert set(result["topic_ids"]) == {t1, t2}


class TestCheckConceptDuplicate:
    def test_no_duplicate_returns_none(self):
        result = _check_concept_duplicate("Brand New Concept", [])
        assert result is None

    def test_exact_duplicate_detected(self):
        tid = db.add_topic(title="TestTopic")
        db.add_concept(title="Existing Concept", topic_ids=[tid])
        result = _check_concept_duplicate("Existing Concept", [tid])
        assert result is not None
        dup_type, msg = result
        assert dup_type == "exact"
        assert "already exists" in msg

    def test_exact_duplicate_case_insensitive(self):
        tid = db.add_topic(title="TestTopic")
        db.add_concept(title="Existing Concept", topic_ids=[tid])
        result = _check_concept_duplicate("existing concept", [tid])
        assert result is not None
        assert result[0] == "exact"

    def test_different_concept_passes(self):
        tid = db.add_topic(title="TestTopic")
        db.add_concept(title="Chromium Oxide", topic_ids=[tid])
        result = _check_concept_duplicate("Molybdenum Disulfide", [tid])
        assert result is None


class TestAddConceptDedup:
    def test_first_add_succeeds(self):
        tid = db.add_topic(title="TestTopic")
        msg_type, result = execute_action(
            "add_concept",
            {
                "title": "New Concept",
                "topic_ids": [tid],
            },
        )
        assert msg_type == "reply"
        assert "Added concept" in result
        assert "(#" in result

    def test_duplicate_add_reuses_existing(self):
        tid = db.add_topic(title="TestTopic")
        msg_type1, result1 = execute_action(
            "add_concept",
            {
                "title": "Duplicate Test",
                "topic_ids": [tid],
            },
        )
        assert msg_type1 == "reply"
        assert "Added concept" in result1

        msg_type2, result2 = execute_action(
            "add_concept",
            {
                "title": "Duplicate Test",
                "topic_ids": [tid],
            },
        )
        assert msg_type2 == "reply"
        assert "already exists" in result2

    def test_duplicate_add_links_new_topic(self):
        t1 = db.add_topic(title="Topic A")
        t2 = db.add_topic(title="Topic B")

        execute_action(
            "add_concept",
            {
                "title": "Cross-Topic Concept",
                "topic_ids": [t1],
            },
        )

        msg_type, result = execute_action(
            "add_concept",
            {
                "title": "Cross-Topic Concept",
                "topic_ids": [t2],
            },
        )
        assert msg_type == "reply"
        assert "already exists" in result
        assert "Linked" in result or "linked" in result.lower()

        concept = db.find_concept_by_title("Cross-Topic Concept")
        assert concept is not None
        assert set(concept["topic_ids"]) == {t1, t2}

    def test_case_insensitive_duplicate_caught(self):
        tid = db.add_topic(title="TestTopic")
        execute_action(
            "add_concept",
            {
                "title": "Embedded Bootloader",
                "topic_ids": [tid],
            },
        )
        msg_type, result = execute_action(
            "add_concept",
            {
                "title": "embedded bootloader",
                "topic_ids": [tid],
            },
        )
        assert msg_type == "reply"
        assert "already exists" in result

    def test_different_concept_creates_fine(self):
        tid = db.add_topic(title="TestTopic")
        execute_action(
            "add_concept",
            {
                "title": "Concept Alpha",
                "topic_ids": [tid],
            },
        )
        msg_type, result = execute_action(
            "add_concept",
            {
                "title": "Concept Beta",
                "topic_ids": [tid],
            },
        )
        assert msg_type == "reply"
        assert "Added concept" in result
        assert "Beta" in result


class TestDBUniqueConstraint:
    def test_unique_index_prevents_duplicate_insert(self):
        """If the application-level guard is bypassed, the DB still reuses the row."""
        tid = db.add_topic(title="TestTopic")

        cid1 = db.add_concept(title="DB Guard Test", topic_ids=[tid])
        assert cid1 > 0

        cid2 = db.add_concept(title="DB Guard Test", topic_ids=[tid])
        assert cid2 == cid1

    def test_unique_index_case_insensitive(self):
        tid = db.add_topic(title="TestTopic")
        cid1 = db.add_concept(title="Case Test", topic_ids=[tid])
        cid2 = db.add_concept(title="case test", topic_ids=[tid])
        assert cid2 == cid1


class TestConceptCountIntegrity:
    def test_rapid_adds_produce_only_one_concept(self):
        """Repeated add_concept calls for the same title must not duplicate the row."""
        tid = db.add_topic(title="TestTopic")

        for _ in range(5):
            execute_action(
                "add_concept",
                {
                    "title": "Rapid Fire Concept",
                    "topic_ids": [tid],
                },
            )

        all_concepts = db.search_concepts("Rapid Fire Concept", limit=10)
        assert len(all_concepts) == 1

    def test_search_concepts_falls_back_when_vector_hits_are_stale(self):
        """Stale vector hits should not suppress the SQL fallback path."""
        tid = db.add_topic(title="TestTopic")
        cid = db.add_concept(title="Vector Fallback Concept", topic_ids=[tid])

        with patch(
            "db.vectors.search_similar_concepts",
            return_value=[{"id": 999999, "title": "stale", "score": 0.9}],
        ):
            matches = db.search_concepts("Vector Fallback Concept", limit=10)

        assert len(matches) == 1
        assert matches[0]["id"] == cid
