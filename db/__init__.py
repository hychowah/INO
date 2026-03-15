"""
Database package for Learning Agent.
Re-exports all public functions for backward compatibility.

Import as `import db` — all existing `db.function()` calls continue to work.
Individual submodules can also be imported directly for focused work:
  from db.topics import add_topic, get_topic
  from db.concepts import get_due_concepts
  etc.
"""

# Core: init, helpers, connection
from db.core import (
    DATA_DIR, KNOWLEDGE_DB, CHAT_DB,
    SCHEMA_VERSION,
    init_databases,
    _parse_datetime, _normalize_dt_str, _now_iso,
    _conn, _connection,
)

# Topics
from db.topics import (
    add_topic, get_topic, update_topic, delete_topic,
    link_topics, get_all_topics, get_topic_relations,
    get_topic_children, get_topic_parents,
    search_topics,
    get_topic_map, get_hierarchical_topic_map,
)

# Concepts
from db.concepts import (
    add_concept, get_concept, update_concept, delete_concept,
    link_concept, unlink_concept,
    get_concepts_for_topic, get_due_concepts, get_next_review_concept,
    get_all_concepts_summary, get_all_concepts_with_topics,
    search_concepts,
    get_concept_detail,
)

# Reviews & Remarks
from db.reviews import (
    add_remark, get_remarks, get_latest_remark,
    add_review, get_recent_reviews, get_review_stats,
)

# Chat & Session
from db.chat import (
    add_chat_message, get_chat_history, clear_chat_history,
    set_session, get_session, clear_session,
)

# Diagnostics
from db.diagnostics import (
    _title_similarity, _stem, _STOP_WORDS,
    get_maintenance_diagnostics,
)

# Proposals (confirmation flows)
from db.proposals import (
    save_proposal, get_proposal, get_pending_proposal,
    update_proposal_message_id, delete_proposal,
    cleanup_expired as cleanup_expired_proposals,
)

# Preferences (persona selection)
from db.preferences import (
    get_available_personas, get_persona, set_persona,
    get_persona_content,
    PERSONAS_DIR, DEFAULT_PERSONA,
)


# ============================================================================
# Self-test
# ============================================================================

if __name__ == '__main__':
    print("Initializing databases...")
    init_databases()
    print(f"  knowledge.db: {KNOWLEDGE_DB}")
    print(f"  chat_history.db: {CHAT_DB}")

    print("\n--- Self-test ---")

    # Topics
    t1 = add_topic("Material Science", "Study of materials and their properties")
    t2 = add_topic("Stainless Steel", "Iron alloys with chromium", parent_ids=[t1])
    t3 = add_topic("Corrosion Engineering", "Study of corrosion and prevention", parent_ids=[t1])
    print(f"Created topics: Material Science(#{t1}), Stainless Steel(#{t2}), Corrosion(#{t3})")

    # Concepts
    c1 = add_concept("Chromium oxide passivation", "Cr2O3 layer protects against rust",
                      topic_ids=[t2, t3])
    c2 = add_concept("Austenitic vs ferritic grades", "Different crystal structures in SS",
                      topic_ids=[t2])
    c3 = add_concept("Galvanic corrosion", "Electrochemical process between dissimilar metals",
                      topic_ids=[t3])
    print(f"Created concepts: #{c1}, #{c2}, #{c3}")

    link_concept(c3, [t1])
    print(f"Linked concept #{c3} to topic #{t1}")

    topic_map = get_topic_map()
    print(f"\nTopic map ({len(topic_map)} topics):")
    for t in topic_map:
        print(f"  [{t['id']}] {t['title']}: {t['concept_count']} concepts, "
              f"avg mastery {t['avg_mastery']}, {t['due_count']} due, "
              f"parents={t['parent_ids']}, children={t['child_ids']}")

    concepts = get_concepts_for_topic(t2)
    print(f"\nConcepts under '{get_topic(t2)['title']}': {[c['title'] for c in concepts]}")

    due = get_due_concepts()
    print(f"\nDue for review: {len(due)} concepts")

    add_remark(c1, "User explained this well — focus on why Cr specifically")
    remark = get_latest_remark(c1)
    print(f"\nLatest remark for concept #{c1}: {remark}")

    add_review(c1, "What protects stainless steel from rusting?",
               "The chromium oxide layer", 4, "Good answer — mentioned Cr2O3 correctly")
    reviews = get_recent_reviews(c1)
    print(f"Reviews for concept #{c1}: {len(reviews)}")

    detail = get_concept_detail(c1)
    print(f"\nConcept detail #{c1}: {detail['title']}")
    print(f"  Topics: {[t['title'] for t in detail['topics']]}")
    print(f"  Remarks: {len(detail['remarks'])}")
    print(f"  Reviews: {len(detail['recent_reviews'])}")

    results = search_concepts("corrosion")
    print(f"\nSearch 'corrosion': {[r['title'] for r in results]}")

    add_chat_message("user", "Why is stainless steel rust-proof?")
    add_chat_message("assistant", "Stainless steel contains chromium which forms Cr2O3...")
    history = get_chat_history()
    print(f"\nChat history: {len(history)} messages")

    stats = get_review_stats()
    print(f"\nStats: {stats}")

    # Cleanup test data
    for cid in [c1, c2, c3]:
        delete_concept(cid)
    for tid in [t3, t2, t1]:
        delete_topic(tid)
    clear_chat_history()

    print("\n--- Self-test passed, test data cleaned up ---")
