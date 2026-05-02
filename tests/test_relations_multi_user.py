"""Focused multi-user scoping tests for db.relations."""

import db
from db.relations import add_relation, add_relations_from_assess, get_all_relations, get_relations, remove_relation, search_related


def test_add_relation_rejects_cross_user_pair(test_db):
    topic_a = db.add_topic("Topic A", user_id="user_a")
    topic_b = db.add_topic("Topic B", user_id="user_b")
    concept_a = db.add_concept("Concept A", topic_ids=[topic_a], user_id="user_a")
    concept_b = db.add_concept("Concept B", topic_ids=[topic_b], user_id="user_b")

    assert add_relation(concept_a, concept_b, user_id="user_a") is None
    assert get_all_relations(user_id="user_a") == []
    assert get_all_relations(user_id="user_b") == []


def test_get_relations_hides_other_users_graph(test_db):
    topic_a = db.add_topic("Topic A", user_id="user_a")
    topic_b = db.add_topic("Topic B", user_id="user_b")
    a1 = db.add_concept("A1", topic_ids=[topic_a], user_id="user_a")
    a2 = db.add_concept("A2", topic_ids=[topic_a], user_id="user_a")
    b1 = db.add_concept("B1", topic_ids=[topic_b], user_id="user_b")
    b2 = db.add_concept("B2", topic_ids=[topic_b], user_id="user_b")

    assert add_relation(a1, a2, user_id="user_a") is not None
    assert add_relation(b1, b2, user_id="user_b") is not None

    assert len(get_relations(a1, user_id="user_a")) == 1
    assert get_relations(a1, user_id="user_b") == []
    assert len(get_all_relations(user_id="user_a")) == 1
    assert len(get_all_relations(user_id="user_b")) == 1


def test_remove_relation_respects_user_scope(test_db):
    topic = db.add_topic("Scoped Topic", user_id="owner")
    c1 = db.add_concept("Owner A", topic_ids=[topic], user_id="owner")
    c2 = db.add_concept("Owner B", topic_ids=[topic], user_id="owner")
    add_relation(c1, c2, user_id="owner")

    assert remove_relation(c1, c2, user_id="other") is False
    assert len(get_relations(c1, user_id="owner")) == 1
    assert remove_relation(c1, c2, user_id="owner") is True


def test_add_relations_from_assess_skips_other_users_concepts(test_db):
    topic_a = db.add_topic("Topic A", user_id="user_a")
    topic_b = db.add_topic("Topic B", user_id="user_b")
    source = db.add_concept("Source", topic_ids=[topic_a], user_id="user_a")
    owned = db.add_concept("Owned", topic_ids=[topic_a], user_id="user_a")
    foreign = db.add_concept("Foreign", topic_ids=[topic_b], user_id="user_b")

    count = add_relations_from_assess(source, [owned, foreign], user_id="user_a")

    assert count == 1
    rels = get_relations(source, user_id="user_a")
    assert len(rels) == 1
    assert rels[0]["other_concept_id"] == owned


def test_search_related_is_user_scoped(test_db):
    topic_a = db.add_topic("Topic A", user_id="user_a")
    topic_b = db.add_topic("Topic B", user_id="user_b")
    a1 = db.add_concept("A1", topic_ids=[topic_a], user_id="user_a")
    a2 = db.add_concept("A2", topic_ids=[topic_a], user_id="user_a")
    b1 = db.add_concept("B1", topic_ids=[topic_b], user_id="user_b")
    b2 = db.add_concept("B2", topic_ids=[topic_b], user_id="user_b")

    add_relation(a1, a2, user_id="user_a")
    add_relation(b1, b2, user_id="user_b")

    results_a = search_related(a1, depth=2, user_id="user_a")
    results_b = search_related(a1, depth=2, user_id="user_b")

    assert [result["id"] for result in results_a] == [a2]
    assert results_b == []