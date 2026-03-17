"""
Tests for topic hierarchy: cycle detection in link_topics, unlink_topics.
"""

import pytest
import db


# ============================================================================
# Helpers
# ============================================================================

def _make_topic(title="Topic"):
    return db.add_topic(title)


# ============================================================================
# Cycle detection in link_topics
# ============================================================================

class TestCycleDetection:
    def test_self_link_rejected(self, test_db):
        t1 = _make_topic("A")
        assert db.link_topics(t1, t1) is False

    def test_direct_cycle_rejected(self, test_db):
        """A→B already exists. B→A should be rejected."""
        t1 = _make_topic("A")
        t2 = _make_topic("B")
        assert db.link_topics(t1, t2) is True
        assert db.link_topics(t2, t1) is False

    def test_transitive_cycle_rejected(self, test_db):
        """A→B→C exists. C→A should be rejected."""
        t1 = _make_topic("A")
        t2 = _make_topic("B")
        t3 = _make_topic("C")
        db.link_topics(t1, t2)
        db.link_topics(t2, t3)
        assert db.link_topics(t3, t1) is False

    def test_long_chain_cycle_rejected(self, test_db):
        """A→B→C→D→E exists. E→A should be rejected."""
        topics = [_make_topic(f"T{i}") for i in range(5)]
        for i in range(4):
            db.link_topics(topics[i], topics[i + 1])
        assert db.link_topics(topics[4], topics[0]) is False

    def test_valid_link_allowed(self, test_db):
        """A→B, A→C — linking C→D should be fine (no cycle)."""
        a = _make_topic("A")
        b = _make_topic("B")
        c = _make_topic("C")
        d = _make_topic("D")
        db.link_topics(a, b)
        db.link_topics(a, c)
        assert db.link_topics(c, d) is True

    def test_diamond_no_false_positive(self, test_db):
        """A→B, A→C, B→D, C→D — diamond is valid DAG, not a cycle."""
        a = _make_topic("A")
        b = _make_topic("B")
        c = _make_topic("C")
        d = _make_topic("D")
        db.link_topics(a, b)
        db.link_topics(a, c)
        db.link_topics(b, d)
        assert db.link_topics(c, d) is True  # diamond, not a cycle

    def test_duplicate_link_ignored(self, test_db):
        """Adding the same link twice should succeed (INSERT OR IGNORE)."""
        t1 = _make_topic("A")
        t2 = _make_topic("B")
        assert db.link_topics(t1, t2) is True
        assert db.link_topics(t1, t2) is True  # idempotent


# ============================================================================
# unlink_topics
# ============================================================================

class TestUnlinkTopics:
    def test_unlink_existing(self, test_db):
        t1 = _make_topic("A")
        t2 = _make_topic("B")
        db.link_topics(t1, t2)
        assert db.unlink_topics(t1, t2) is True

        # Verify the link is gone
        children = db.get_topic_children(t1)
        assert len(children) == 0

    def test_unlink_nonexistent(self, test_db):
        t1 = _make_topic("A")
        t2 = _make_topic("B")
        assert db.unlink_topics(t1, t2) is False

    def test_unlink_allows_re_link(self, test_db):
        """After unlinking, should be able to link again."""
        t1 = _make_topic("A")
        t2 = _make_topic("B")
        db.link_topics(t1, t2)
        db.unlink_topics(t1, t2)
        assert db.link_topics(t1, t2) is True

    def test_unlink_one_of_multiple_parents(self, test_db):
        """Topic with two parents: unlinking one should keep the other."""
        parent1 = _make_topic("Parent1")
        parent2 = _make_topic("Parent2")
        child = _make_topic("Child")
        db.link_topics(parent1, child)
        db.link_topics(parent2, child)

        db.unlink_topics(parent1, child)

        parents = db.get_topic_parents(child)
        assert len(parents) == 1
        assert parents[0]['id'] == parent2
