"""Integration coverage for real pipeline -> tools handler execution paths."""

from unittest.mock import AsyncMock, patch

import pytest

import db
from db import action_log
from services.pipeline import execute_llm_response
from services import tools


@pytest.mark.anyio
async def test_add_topic_via_execute_llm_response_creates_topic_and_logs(test_db):
    llm_response = '{"action": "add_topic", "params": {"title": "Databases"}}'

    with patch("services.pipeline.repair_action", new=AsyncMock(return_value=None)):
        result = await execute_llm_response("Please add a topic", llm_response)

    created = db.find_topic_by_title("Databases")
    entries = action_log.get_action_log(action_filter="add_topic")

    assert result == f"REPLY: Created topic **Databases** (#{created['id']})"
    assert created is not None
    assert entries[0]["action"] == "add_topic"
    assert '"title": "Databases"' in entries[0]["params"]


@pytest.mark.anyio
async def test_add_concept_via_execute_llm_response_creates_concept_and_logs(test_db):
    topic_id = db.add_topic("Databases")
    llm_response = (
        '{"action": "add_concept", "params": '
        '{"title": "B-Tree", "description": "Balanced index", "topic_ids": ['
        f"{topic_id}"
        "]}}"
    )

    with (
        patch("services.pipeline.repair_action", new=AsyncMock(return_value=None)),
        patch("db.vectors.upsert_concept"),
    ):
        result = await execute_llm_response("Please add a concept", llm_response)

    created = db.find_concept_by_title("B-Tree")
    detail = db.get_concept_detail(created["id"])
    entries = action_log.get_action_log(action_filter="add_concept")

    assert result == (
        f"REPLY: Added concept **B-Tree** (#{created['id']}) under Databases. "
        "First review scheduled for tomorrow."
    )
    assert created is not None
    assert detail["description"] == "Balanced index"
    assert [topic["id"] for topic in detail["topics"]] == [topic_id]
    assert entries[0]["action"] == "add_concept"
    assert '"title": "B-Tree"' in entries[0]["params"]


def test_update_concept_resolves_by_title(test_db):
    concept_id = db.add_concept("B-Tree", "Balanced index")

    msg_type, result = tools.execute_action(
        "update_concept",
        {
            "title": "B-Tree",
            "description": "Balanced search tree index",
        },
    )

    detail = db.get_concept_detail(concept_id)
    assert msg_type == "reply"
    assert result == f"Updated concept #{concept_id}"
    assert detail["description"] == "Balanced search tree index"


def test_remark_resolves_by_title(test_db):
    concept_id = db.add_concept("Hash Index", "Fast lookup structure")

    msg_type, result = tools.execute_action(
        "remark",
        {
            "title": "Hash Index",
            "content": "Remember the equality-only tradeoff.",
        },
    )

    detail = db.get_concept_detail(concept_id)
    assert msg_type == "reply"
    assert result == f"Added remark to concept #{concept_id}"
    assert any(
        "equality-only tradeoff" in remark["content"]
        for remark in detail.get("remarks", [])
    )
