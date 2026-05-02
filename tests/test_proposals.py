"""Tests for user-scoped pending proposal persistence."""

import db
from services import state


def test_pending_proposal_is_scoped_by_explicit_user(test_db):
    proposal_a = db.save_proposal("dedup", [{"keep": 1, "merge": [2]}], user_id="user_a")
    proposal_b = db.save_proposal("dedup", [{"keep": 3, "merge": [4]}], user_id="user_b")

    pending_a = db.get_pending_proposal("dedup", user_id="user_a")
    pending_b = db.get_pending_proposal("dedup", user_id="user_b")

    assert pending_a is not None
    assert pending_b is not None
    assert pending_a["id"] == proposal_a
    assert pending_b["id"] == proposal_b
    assert pending_a["user_id"] == "user_a"
    assert pending_b["user_id"] == "user_b"


def test_get_proposal_uses_context_user_by_default(test_db):
    proposal_id = db.save_proposal("maintenance", [{"action": "delete_topic", "params": {"topic_id": 1}}], user_id="ctx_user")

    previous_user = state.get_current_user()
    state.set_current_user("ctx_user")
    try:
        proposal = db.get_proposal(proposal_id)
        assert proposal is not None
        assert proposal["user_id"] == "ctx_user"
        assert proposal["proposal_type"] == "maintenance"
    finally:
        state.set_current_user(previous_user)


def test_get_proposal_hides_other_users_proposal(test_db):
    proposal_id = db.save_proposal("taxonomy", [{"action": "link_topics", "params": {"parent_id": 1, "child_id": 2}}], user_id="owner")

    assert db.get_proposal(proposal_id, user_id="other") is None
    assert db.get_pending_proposal("taxonomy", user_id="other") is None


def test_delete_proposal_only_removes_matching_user(test_db):
    proposal_a = db.save_proposal("dedup", [{"keep": 1, "merge": [2]}], user_id="user_a")
    proposal_b = db.save_proposal("dedup", [{"keep": 3, "merge": [4]}], user_id="user_b")

    db.delete_proposal(proposal_a, user_id="user_b")

    assert db.get_proposal(proposal_a, user_id="user_a") is not None
    assert db.get_proposal(proposal_b, user_id="user_b") is not None

    db.delete_proposal(proposal_a, user_id="user_a")
    assert db.get_proposal(proposal_a, user_id="user_a") is None


def test_update_proposal_payload_replaces_payload_for_matching_user(test_db):
    proposal_id = db.save_proposal(
        "maintenance",
        [
            {"action": "update_topic", "_proposal_item_id": "maintenance-0"},
            {"action": "delete_topic", "_proposal_item_id": "maintenance-1"},
        ],
        user_id="owner",
    )

    db.update_proposal_payload(
        proposal_id,
        [{"action": "delete_topic", "_proposal_item_id": "maintenance-1"}],
        user_id="owner",
    )

    proposal = db.get_proposal(proposal_id, user_id="owner")
    assert proposal is not None
    assert proposal["payload"] == [
        {"action": "delete_topic", "_proposal_item_id": "maintenance-1"}
    ]
