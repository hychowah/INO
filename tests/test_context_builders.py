"""Direct tests for context builder helpers not covered by enrichment tests."""

from unittest.mock import patch

import db
from db import action_log
from services.context import build_maintenance_context, build_taxonomy_context, format_fetch_result


def test_format_fetch_result_topic_payload_includes_hierarchy_and_concepts(test_db):
    topic_payload = {
        "topic": {"id": 3, "title": "Databases", "description": "Data storage systems"},
        "parent_topics": [{"id": 1, "title": "Computer Science"}],
        "child_topics": [{"id": 4, "title": "Indexing"}],
        "concepts": [
            {
                "id": 8,
                "title": "B-Tree",
                "mastery_level": 55,
                "next_review_at": "2026-04-16 09:00:00",
                "latest_remark": "Solid on branching factor",
            }
        ],
    }

    rendered = format_fetch_result(topic_payload)

    assert "### Topic: Databases (#3)" in rendered
    assert "Parents: ['Computer Science']" in rendered
    assert "Children: ['Indexing']" in rendered
    assert "Concepts (1):" in rendered
    assert (
        "  - [concept:8] B-Tree (score 55/100, next: 2026-04-16 09:00:00 | "
        "Solid on branching factor)"
    ) in rendered


def test_format_fetch_result_concept_payload_includes_remark_reviews_and_relations(test_db):
    concept_payload = {
        "concept_detail": {
            "id": 5,
            "title": "B-Tree",
            "description": "Balanced search tree",
            "mastery_level": 55,
            "interval_days": 7,
            "review_count": 3,
            "topics": [{"title": "Databases"}],
            "next_review_at": "2026-04-20 09:00:00",
            "remark_summary": "Needs a cleaner explanation of split propagation.",
            "remark_updated_at": "2026-04-15 08:30:00",
            "recent_reviews": [
                {
                    "question_asked": "What problem does a B-Tree solve?",
                    "user_response": "It keeps index operations efficient on disk.",
                    "quality": 4,
                    "llm_assessment": "Correct core idea.",
                }
            ],
        }
    }

    with patch.object(
        db,
        "get_relations",
        return_value=[
            {
                "relation_type": "builds_on",
                "other_concept_id": 9,
                "other_title": "Indexes",
                "other_mastery": 72,
            }
        ],
    ):
        rendered = format_fetch_result(concept_payload)

    assert "### Concept: B-Tree (#5)" in rendered
    assert "Remark summary (updated 2026-04-15 08:30:00):" in rendered
    assert "Needs a cleaner explanation of split propagation." in rendered
    assert "Recent reviews:" in rendered
    assert "Quality: 4/5 — Correct core idea." in rendered
    assert "Related Concepts:" in rendered
    assert "[concept:9] Indexes (score 72/100)" in rendered


def test_build_maintenance_context_renders_detected_issue_sections(test_db):
    db.add_topic("Empty Topic")
    db.add_concept("Untagged Concept", "No topic assigned")

    rendered = build_maintenance_context()

    assert "### Overview" in rendered
    assert "### ⚠️ Untagged Concepts (1)" in rendered
    assert "- [concept:" in rendered and "Untagged Concept" in rendered
    assert "### ⚠️ Empty Topics (1)" in rendered
    assert "- [topic:" in rendered and "Empty Topic" in rendered


def test_build_taxonomy_context_includes_suppressed_renames(test_db):
    topic_id = db.add_topic("Databases")
    action_log.log_action(
        "update_topic",
        {"topic_id": topic_id, "title": "Data Systems"},
        "rejected",
        "user rejected rename",
        source="maintenance",
    )

    rendered = build_taxonomy_context()

    assert "### ⛔ Suppressed Renames (do NOT propose these again)" in rendered
    assert f'- [topic:{topic_id}] → "Data Systems"' in rendered
    assert "### Root Topics (candidates for new parent grouping)" in rendered
