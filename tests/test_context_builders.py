"""Direct tests for context builder helpers not covered by enrichment tests."""

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
