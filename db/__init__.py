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
# Action Log (audit trail)
from db.action_log import (
    cleanup_old_actions,
    get_action_log,
    get_action_log_count,
    get_action_summary,
    get_distinct_actions,
    get_distinct_sources,
    log_action,
)

# Chat & Session
from db.chat import (
    add_chat_message,
    clear_chat_history,
    clear_session,
    get_chat_history,
    get_session,
    get_session_updated_at,
    set_session,
)

# Concepts
from db.concepts import (
    add_concept,
    delete_concept,
    find_concept_by_title,
    get_all_concepts_summary,
    get_all_concepts_with_topics,
    get_concept,
    get_concept_detail,
    get_concept_topic_edges,
    get_concepts_for_topic,
    get_due_concepts,
    get_due_count,
    get_due_forecast,
    get_forecast_bucket_concepts,
    get_next_review_concept,
    link_concept,
    search_concepts,
    unlink_concept,
    update_concept,
)
from db.core import (
    CHAT_DB,
    DATA_DIR,
    KNOWLEDGE_DB,
    SCHEMA_VERSION,
    _conn,
    _connection,
    _normalize_dt_str,
    _now_iso,
    _parse_datetime,
    init_databases,
)

# Diagnostics
from db.diagnostics import (
    _STOP_WORDS,
    _stem,
    _title_similarity,
    get_maintenance_diagnostics,
)

# Preferences (persona selection)
from db.preferences import (
    DEFAULT_PERSONA,
    PERSONAS_DIR,
    get_available_personas,
    get_persona,
    get_persona_content,
    set_persona,
)
from db.proposals import (
    cleanup_expired as cleanup_expired_proposals,
)

# Proposals (confirmation flows)
from db.proposals import (
    delete_proposal,
    get_pending_proposal,
    get_proposal,
    save_proposal,
    update_proposal_message_id,
)

# Concept Relations (cross-concept edges)
from db.relations import (
    MAX_RELATIONS_PER_CONCEPT,
    VALID_RELATION_TYPES,
    add_relation,
    add_relations_from_assess,
    get_all_relations,
    get_relations,
    remove_relation,
    search_related,
)

# Reviews & Remarks
from db.reviews import (
    add_remark,
    add_review,
    get_latest_remark,
    get_recent_reviews,
    get_remarks,
    get_review_stats,
)

# Topics
from db.topics import (
    add_topic,
    delete_topic,
    find_topic_by_title,
    get_all_topics,
    get_hierarchical_topic_map,
    get_topic,
    get_topic_children,
    get_topic_map,
    get_topic_parents,
    get_topic_relations,
    link_topics,
    search_topics,
    unlink_topics,
    update_topic,
)

# Vector store (semantic search)
try:
    from db.vectors import (
        concept_similarity,
        find_nearest_concepts,
        search_similar_concepts,
        search_similar_topics,
    )
    from db.vectors import (
        delete_concept as vector_delete_concept,
    )
    from db.vectors import (
        delete_topic as vector_delete_topic,
    )
    from db.vectors import (
        get_collection_count as vector_collection_count,
    )
    from db.vectors import (
        reindex_all as vector_reindex_all,
    )
    from db.vectors import (
        upsert_concept as vector_upsert_concept,
    )
    from db.vectors import (
        upsert_topic as vector_upsert_topic,
    )

    VECTORS_AVAILABLE = True
except ImportError:
    VECTORS_AVAILABLE = False


# ============================================================================
# Self-test
# ============================================================================

if __name__ == "__main__":
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
    c1 = add_concept(
        "Chromium oxide passivation", "Cr2O3 layer protects against rust", topic_ids=[t2, t3]
    )
    c2 = add_concept(
        "Austenitic vs ferritic grades", "Different crystal structures in SS", topic_ids=[t2]
    )
    c3 = add_concept(
        "Galvanic corrosion", "Electrochemical process between dissimilar metals", topic_ids=[t3]
    )
    print(f"Created concepts: #{c1}, #{c2}, #{c3}")

    link_concept(c3, [t1])
    print(f"Linked concept #{c3} to topic #{t1}")

    topic_map = get_topic_map()
    print(f"\nTopic map ({len(topic_map)} topics):")
    for t in topic_map:
        print(
            f"  [{t['id']}] {t['title']}: {t['concept_count']} concepts, "
            f"avg mastery {t['avg_mastery']}, {t['due_count']} due, "
            f"parents={t['parent_ids']}, children={t['child_ids']}"
        )

    concepts = get_concepts_for_topic(t2)
    print(f"\nConcepts under '{get_topic(t2)['title']}': {[c['title'] for c in concepts]}")

    due = get_due_concepts()
    print(f"\nDue for review: {len(due)} concepts")

    add_remark(c1, "User explained this well — focus on why Cr specifically")
    remark = get_latest_remark(c1)
    print(f"\nLatest remark for concept #{c1}: {remark}")

    # Verify remark_summary cache was populated
    detail = get_concept_detail(c1)
    assert detail.get("remark_summary") is not None, "remark_summary cache not populated!"
    print(f"  remark_summary cache: {detail['remark_summary'][:60]}...")

    add_review(
        c1,
        "What protects stainless steel from rusting?",
        "The chromium oxide layer",
        4,
        "Good answer — mentioned Cr2O3 correctly",
    )
    reviews = get_recent_reviews(c1)
    print(f"Reviews for concept #{c1}: {len(reviews)}")

    detail = get_concept_detail(c1)
    print(f"\nConcept detail #{c1}: {detail['title']}")
    print(f"  Topics: {[t['title'] for t in detail['topics']]}")
    print(f"  Remarks (history): {len(detail['remarks'])}")
    print(f"  Remark summary: {detail.get('remark_summary', 'N/A')[:60]}")
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
