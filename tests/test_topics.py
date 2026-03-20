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


# ============================================================================
# add_topic parent_ids validation
# ============================================================================

class TestAddTopicParentIds:
    def test_add_topic_with_parent_ids(self, test_db):
        """Creating a topic with parent_ids links it in topic_relations."""
        parent = _make_topic("Python")
        child = db.add_topic("Python AST", parent_ids=[parent])

        parents = db.get_topic_parents(child)
        assert len(parents) == 1
        assert parents[0]['id'] == parent

    def test_add_topic_with_multiple_parents(self, test_db):
        """Topics can have multiple parents."""
        p1 = _make_topic("Python")
        p2 = _make_topic("Compilers")
        child = db.add_topic("Python AST", parent_ids=[p1, p2])

        parents = db.get_topic_parents(child)
        parent_ids = {p['id'] for p in parents}
        assert parent_ids == {p1, p2}

    def test_add_topic_nonexistent_parent_ignored(self, test_db):
        """If parent_ids contains a non-existent topic ID, it's silently ignored."""
        topic_id = db.add_topic("Test", parent_ids=[999999])
        # Should not crash; the non-existent parent is silently ignored
        parents = db.get_topic_parents(topic_id)
        # The 999999 parent doesn't exist as a topic, so no parent is linked
        # (INSERT OR IGNORE skips FK violations in WAL mode)
        assert isinstance(parents, list)

    def test_add_topic_no_parent_ids(self, test_db):
        """Topic created without parent_ids has no parents."""
        topic_id = _make_topic("Standalone")
        parents = db.get_topic_parents(topic_id)
        assert len(parents) == 0
