"""Additional scheduler branch coverage beyond quiz-send behavior."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

import db
from services import scheduler, state


def _set_pending_review(concept_id: int, reminder_count: int = 0, *, hours_ago: int = 5):
    db.set_session(
        "pending_review",
        json.dumps(
            {
                "concept_id": concept_id,
                "concept_title": "Pending Concept",
                "question": "What is it?",
                "sent_at": (datetime.now() - timedelta(hours=hours_ago)).isoformat(),
                "reminder_count": reminder_count,
            }
        ),
    )


@pytest.mark.anyio
async def test_check_reviews_sends_reminder_before_fetching_new_review(test_db):
    concept_id = db.add_concept("Pending Concept", "Desc")
    _set_pending_review(concept_id)
    original_last_activity = state.last_activity_at
    state.last_activity_at = None

    try:
        with (
            patch("services.scheduler._send_review_reminder", new=AsyncMock()) as reminder_mock,
            patch("services.scheduler.pipeline.handle_review_check") as handle_review_check_mock,
        ):
            await scheduler._check_reviews()

        reminder_mock.assert_awaited_once()
        handle_review_check_mock.assert_not_called()
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
        patch("services.scheduler.pipeline.handle_dedup_check", new=AsyncMock()) as dedup_mock,
    ):
        await scheduler._check_dedup()

    pending_mock.assert_called_once_with("dedup")
    dedup_mock.assert_not_called()


@pytest.mark.anyio
async def test_check_dedup_sends_suggestions_for_found_groups(test_db):
    groups = [{"title": "Group 1", "concept_ids": [1, 2]}]

    with (
        patch("services.scheduler.db.get_pending_proposal", return_value=None),
        patch("services.scheduler.pipeline.handle_dedup_check", new=AsyncMock(return_value=groups)),
        patch("services.scheduler.db.save_proposal", return_value=12) as save_mock,
        patch.object(scheduler, "_bot", object()),
        patch.object(scheduler, "_authorized_user_id", 123),
        patch("services.scheduler._send_dedup_suggestions", new=AsyncMock()) as send_mock,
    ):
        await scheduler._check_dedup()

    save_mock.assert_called_once_with("dedup", groups)
    send_mock.assert_awaited_once_with(12, groups)
