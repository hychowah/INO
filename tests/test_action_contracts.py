import pytest

from services.action_contracts import build_action_json_schema, validate_action_contract

pytestmark = pytest.mark.unit


def test_validates_missing_required_action_params():
    errors = validate_action_contract(
        {"action": "assess", "params": {"concept_id": 1}, "message": "feedback"},
        valid_actions={"assess"},
    )

    assert "assess requires params.quality" in errors


def test_validates_fetch_cluster_requires_concept_id():
    errors = validate_action_contract(
        {"action": "fetch", "params": {"cluster": True}, "message": "loading"},
        valid_actions={"fetch"},
    )

    assert "fetch with cluster requires params.concept_id" in errors


def test_accepts_top_level_message_for_reply_action():
    errors = validate_action_contract(
        {"action": "reply", "params": {}, "message": "Clean answer."},
        valid_actions={"reply"},
    )

    assert errors == []


def test_accepts_intish_string_for_ids():
    errors = validate_action_contract(
        {"action": "delete_topic", "params": {"topic_id": "12"}, "message": "Deleted."},
        valid_actions={"delete_topic"},
    )

    assert errors == []


def test_rejects_wrong_param_type():
    errors = validate_action_contract(
        {"action": "link_concept", "params": {"concept_id": 1, "topic_ids": "bad"}},
        valid_actions={"link_concept"},
    )

    assert "params.topic_ids must be a list" in errors


def test_build_action_json_schema_uses_valid_action_enum():
    schema = build_action_json_schema({"reply", "assess"})

    assert schema["name"] == "learning_agent_turn"
    assert schema["schema"]["properties"]["action"]["enum"] == ["assess", "reply"]
    assert schema["schema"]["required"] == ["action", "params", "message"]
