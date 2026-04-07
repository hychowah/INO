import asyncio
import importlib

import pytest

from scripts import taxonomy_shadow_rebuild as rebuild
from services import pipeline


def test_topic_map_signature_normalizes_order():
    topic_map = [
        {
            "id": 2,
            "title": "Child",
            "description": None,
            "concept_count": 1,
            "parent_ids": [1],
            "child_ids": [],
        },
        {
            "id": 1,
            "title": "Root",
            "description": "desc",
            "concept_count": 3,
            "parent_ids": [],
            "child_ids": [2],
        },
    ]

    assert rebuild._topic_map_signature(topic_map) == [
        {
            "id": 1,
            "title": "Root",
            "description": "desc",
            "concept_count": 3,
            "parent_ids": [],
            "child_ids": [2],
        },
        {
            "id": 2,
            "title": "Child",
            "description": None,
            "concept_count": 1,
            "parent_ids": [1],
            "child_ids": [],
        },
    ]


def test_vector_store_path_env_override(monkeypatch, tmp_path):
    import config

    override = tmp_path / "shadow_vectors"
    monkeypatch.setenv("LEARN_VECTOR_STORE_PATH", str(override))
    importlib.reload(config)
    try:
        assert config.VECTOR_STORE_PATH == override
    finally:
        monkeypatch.delenv("LEARN_VECTOR_STORE_PATH", raising=False)
        importlib.reload(config)


def test_call_taxonomy_loop_forwards_overrides(monkeypatch):
    captured = {}

    async def fake_call_action_loop(**kwargs):
        captured.update(kwargs)
        return "REPLY: ok", []

    monkeypatch.setattr(pipeline, "call_action_loop", fake_call_action_loop)

    journal = []
    report, proposed = asyncio.run(
        pipeline.call_taxonomy_loop(
            "taxonomy context",
            max_actions=23,
            continuation_context_limit=4096,
            action_journal=journal,
            operator_directive="be aggressive",
        )
    )

    assert report == "REPLY: ok"
    assert proposed == []
    assert captured["mode"] == "taxonomy-mode"
    assert captured["max_actions"] == 23
    assert captured["continuation_context_limit"] == 4096
    assert captured["action_journal"] is journal
    assert captured["preamble"].endswith("## Operator Directive\nbe aggressive")


def test_render_structure_document_markdown_contains_tree():
    topic_map = [
        {
            "id": 1,
            "title": "Root",
            "description": None,
            "concept_count": 3,
            "parent_ids": [],
            "child_ids": [2],
        },
        {
            "id": 2,
            "title": "Child",
            "description": None,
            "concept_count": 1,
            "parent_ids": [1],
            "child_ids": [],
        },
    ]

    rendered = rebuild._render_structure_document(
        title="Preview After",
        summary=rebuild._topic_map_summary(topic_map),
        topic_map=topic_map,
        fmt="md",
    )

    assert "# Preview After" in rendered
    assert "[topic:1] Root (3 concepts)" in rendered
    assert "  [topic:2] Child (1 concepts)" in rendered


def test_write_structure_snapshot_writes_latest_and_archive(tmp_path):
    topic_map = [
        {
            "id": 1,
            "title": "Root",
            "description": None,
            "concept_count": 0,
            "parent_ids": [],
            "child_ids": [],
        }
    ]

    latest_path, stamped_path = rebuild._write_structure_snapshot(
        output_dir=tmp_path,
        run_stamp="2026-04-07_22-00-00",
        label="preview_after",
        fmt="txt",
        summary=rebuild._topic_map_summary(topic_map),
        topic_map=topic_map,
    )

    assert latest_path.exists()
    assert stamped_path.exists()
    assert latest_path.name == "preview_after_latest.txt"
    assert stamped_path.name == "2026-04-07_22-00-00_preview_after.txt"


def test_taxonomy_loop_reuses_session_and_records_created_topic(monkeypatch):
    responses = [
        '{"action": "add_topic", "params": {"title": "Group"}, "message": "Create parent"}',
        '{"action": "link_topics", "params": {"parent_id": 3, "child_id": 2}, "message": "Nest child"}',
        "REPLY: done",
    ]
    seen_sessions = []

    async def fake_call_with_fetch_loop(**kwargs):
        seen_sessions.append((kwargs.get("session"), kwargs.get("is_new_session")))
        return responses.pop(0)

    async def fake_execute_action(_action_data):
        return "REPLY: ok"

    monkeypatch.setattr(pipeline, "call_with_fetch_loop", fake_call_with_fetch_loop)
    monkeypatch.setattr(pipeline, "execute_action", fake_execute_action)
    monkeypatch.setattr(
        pipeline.db,
        "get_session",
        lambda key: "7" if key == "last_added_topic_id" else None,
    )

    journal = []
    report, proposed = asyncio.run(
        pipeline.call_taxonomy_loop(
            "taxonomy context",
            max_actions=3,
            action_journal=journal,
        )
    )

    assert report.startswith("REPLY:")
    assert proposed == []
    assert len(seen_sessions) == 3
    assert seen_sessions[0][0].startswith("taxonomy-mode_")
    assert seen_sessions[0][1] is True
    assert all(session == seen_sessions[0][0] for session, _ in seen_sessions)
    assert seen_sessions[1][1] is False
    assert seen_sessions[2][1] is False
    assert journal[0]["action"] == "add_topic"
    assert journal[0]["created_topic_id"] == 7
    assert journal[0]["replayable"] is True
    assert journal[1]["action"] == "link_topics"
    assert journal[1]["replayable"] is True


def test_replay_action_journal_aborts_on_created_topic_id_mismatch():
    journal = [
        {
            "step": 1,
            "action": "add_topic",
            "action_data": {"action": "add_topic", "params": {"title": "Group"}},
            "replayable": True,
            "created_topic_id": 7,
        }
    ]

    async def fake_execute_action(_action_data):
        return "REPLY: ok"

    with pytest.raises(RuntimeError, match="Topic ID mismatch"):
        asyncio.run(
            rebuild.replay_action_journal(
                journal,
                execute_action=fake_execute_action,
                get_created_topic_id=lambda: 8,
            )
        )