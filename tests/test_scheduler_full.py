"""Additional scheduler branch coverage beyond quiz-send behavior."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

import db
from services import scheduler, state
from services.review_state import register_interactive_review_delivery


def _set_pending_review(concept_id: int, reminder_count: int = 0, *, hours_ago: int = 5):
    sent_at = (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
    db.upsert_scheduled_review_reminder(
        concept_id,
        "What is it?",
        first_sent_at=sent_at,
        last_sent_at=sent_at,
        reminder_count=reminder_count,
    )


@pytest.mark.anyio
async def test_check_reviews_sends_reminder_before_fetching_new_review(test_db):
    concept_id = db.add_concept("Pending Concept", "Desc")
    _set_pending_review(concept_id)
    original_last_activity = state.last_activity_at
    state.last_activity_at = None

    try:
        with (
            patch("services.scheduler._is_within_review_quiet_hours", return_value=False),
            patch("services.scheduler._send_review_reminder", new=AsyncMock()) as reminder_mock,
            patch("services.scheduler._get_scheduled_review_payload") as payload_mock,
        ):
            await scheduler._check_reviews()

        reminder_mock.assert_awaited_once()
        payload_mock.assert_not_called()
    finally:
        state.last_activity_at = original_last_activity


@pytest.mark.anyio
async def test_check_reviews_resends_after_two_hours_when_unanswered(test_db):
    concept_id = db.add_concept("Two Hour Reminder", "Desc")
    db.upsert_scheduled_review_reminder(
        concept_id,
        "What is it?",
        first_sent_at=(datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
        last_sent_at=(datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    original_last_activity = state.last_activity_at
    state.last_activity_at = None

    try:
        with (
            patch("services.scheduler._is_within_review_quiet_hours", return_value=False),
            patch("services.scheduler._send_review_reminder", new=AsyncMock()) as reminder_mock,
            patch("services.scheduler._get_scheduled_review_payload") as payload_mock,
        ):
            await scheduler._check_reviews()

        reminder_mock.assert_awaited_once()
        payload_mock.assert_not_called()
    finally:
        state.last_activity_at = original_last_activity


@pytest.mark.anyio
async def test_check_reviews_reminds_after_unanswered_interactive_delivery(test_db):
    concept_id = db.add_concept("Interactive Pending Concept", "Desc")
    question = "What advantages does LCEL have here?"
    register_interactive_review_delivery(concept_id, question)

    sent_at = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    db.upsert_scheduled_review_reminder(
        concept_id,
        question,
        first_sent_at=sent_at,
        last_sent_at=sent_at,
        reminder_count=0,
    )

    original_last_activity = state.last_activity_at
    state.last_activity_at = None

    try:
        with (
            patch("services.scheduler._is_within_review_quiet_hours", return_value=False),
            patch("services.scheduler._send_review_reminder", new=AsyncMock()) as reminder_mock,
            patch("services.scheduler._get_scheduled_review_payload") as payload_mock,
        ):
            await scheduler._check_reviews()

        reminder_mock.assert_awaited_once()
        reminder = reminder_mock.await_args.args[0]
        assert reminder["concept_id"] == concept_id
        assert reminder["question"] == question
        payload_mock.assert_not_called()
    finally:
        state.last_activity_at = original_last_activity


@pytest.mark.anyio
async def test_check_reviews_clears_deleted_typed_reminder_before_fetching_due_review(test_db):
    stale_concept_id = db.add_concept("Deleted Pending Concept", "Desc")
    fresh_concept_id = db.add_concept("Fresh Due Concept", "Desc")
    _set_pending_review(stale_concept_id)
    assert db.delete_concept(stale_concept_id)

    original_last_activity = state.last_activity_at
    state.last_activity_at = None

    try:
        with (
            patch("services.scheduler.state.get_last_user_activity", return_value=None),
            patch("services.scheduler._is_within_review_quiet_hours", return_value=False),
            patch("services.scheduler._review_in_progress_active", return_value=False),
            patch(
                "services.scheduler._get_scheduled_review_payload",
                return_value=f"{fresh_concept_id}|context",
            ) as payload_mock,
            patch("services.scheduler._send_review_quiz", new=AsyncMock()) as quiz_mock,
        ):
            await scheduler._check_reviews()

        payload_mock.assert_called_once_with()
        quiz_mock.assert_awaited_once_with(f"{fresh_concept_id}|context")
        assert db.get_scheduled_review_reminder() is None
    finally:
        state.last_activity_at = original_last_activity


@pytest.mark.anyio
async def test_check_maintenance_forwards_nonempty_context(test_db):
    with (
        patch("services.scheduler.pipeline.handle_maintenance", return_value="diag") as handle_mock,
        patch("services.scheduler._send_maintenance_report", new=AsyncMock()) as send_mock,
    ):
        await scheduler._check_maintenance()

    handle_mock.assert_called_once_with()
    send_mock.assert_awaited_once_with("diag")


@pytest.mark.anyio
async def test_send_maintenance_report_forwards_loop_output_to_mode_report(test_db):
    with (
        patch(
            "services.scheduler.pipeline.call_maintenance_loop",
            new=AsyncMock(return_value=("REPLY: maintenance summary", [{"action": "update_topic"}])),
        ) as loop_mock,
        patch("services.scheduler._send_mode_report", new=AsyncMock()) as report_mock,
    ):
        await scheduler._send_maintenance_report("diag")

    loop_mock.assert_awaited_once_with("diag")
    report_mock.assert_awaited_once_with(
        mode_label="Knowledge Base Maintenance",
        icon="🔧",
        final_result="REPLY: maintenance summary",
        proposed_actions=[{"action": "update_topic"}],
        proposal_type="maintenance",
    )


@pytest.mark.anyio
async def test_send_taxonomy_report_forwards_loop_output_to_mode_report(test_db):
    with (
        patch(
            "services.scheduler.pipeline.call_taxonomy_loop",
            new=AsyncMock(return_value=("REPLY: taxonomy summary", [{"action": "link_topics"}])),
        ) as loop_mock,
        patch("services.scheduler._send_mode_report", new=AsyncMock()) as report_mock,
    ):
        await scheduler._send_taxonomy_report("taxonomy")

    loop_mock.assert_awaited_once_with("taxonomy")
    report_mock.assert_awaited_once_with(
        mode_label="Weekly Taxonomy Reorganization",
        icon="🌿",
        final_result="REPLY: taxonomy summary",
        proposed_actions=[{"action": "link_topics"}],
        proposal_type="taxonomy",
    )


@pytest.mark.anyio
async def test_check_taxonomy_skips_when_no_topics_found(test_db):
    with (
        patch("services.scheduler.pipeline.handle_taxonomy", return_value="") as handle_mock,
        patch("services.scheduler.pipeline.call_taxonomy_loop", new=AsyncMock()) as taxonomy_loop,
    ):
        await scheduler._check_taxonomy()

    handle_mock.assert_called_once_with()
    taxonomy_loop.assert_not_called()


@pytest.mark.anyio
async def test_check_dedup_skips_when_pending_proposal_exists(test_db):
    with (
        patch("services.scheduler.db.get_pending_proposal", return_value={"id": 5}) as pending_mock,
        patch("services.scheduler.handle_dedup_check", new=AsyncMock()) as dedup_mock,
    ):
        await scheduler._check_dedup()

    pending_mock.assert_called_once_with("dedup")
    dedup_mock.assert_not_called()


@pytest.mark.anyio
async def test_check_dedup_sends_suggestions_for_found_groups(test_db):
    groups = [{"title": "Group 1", "concept_ids": [1, 2]}]

    with (
        patch("services.scheduler.db.get_pending_proposal", return_value=None),
        patch("services.scheduler.handle_dedup_check", new=AsyncMock(return_value=groups)),
        patch("services.scheduler.db.save_proposal", return_value=12) as save_mock,
        patch.object(scheduler, "_bot", object()),
        patch.object(scheduler, "_authorized_user_id", 123),
        patch("services.scheduler._send_dedup_suggestions", new=AsyncMock()) as send_mock,
    ):
        await scheduler._check_dedup()

    save_mock.assert_called_once_with("dedup", groups)
    send_mock.assert_awaited_once_with(12, groups)
