from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
from services import scheduler


@pytest.mark.anyio
async def test_run_due_jobs_persists_success_and_error(test_db):
    del test_db

    success = scheduler._ScheduledJob(
        "success_job",
        lambda: 60,
        AsyncMock(),
    )
    failing = scheduler._ScheduledJob(
        "failing_job",
        lambda: 60,
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    await scheduler._run_due_jobs(
        (success,), db._parse_datetime("2026-04-22 10:00:00"), owner_label="bot"
    )
    await scheduler._run_due_jobs(
        (failing,), db._parse_datetime("2026-04-22 10:05:00"), owner_label="api"
    )

    success_row = db.get_scheduler_state("success_job")
    failing_row = db.get_scheduler_state("failing_job")

    assert success_row is not None
    assert success_row["last_run_at"] == "2026-04-22 10:00:00"
    assert success_row["last_success_at"] == "2026-04-22 10:00:00"
    assert success_row["last_error"] is None

    assert failing_row is not None
    assert failing_row["last_run_at"] == "2026-04-22 10:05:00"
    assert failing_row["last_success_at"] is None
    assert failing_row["last_error"] == "boom"


@pytest.mark.anyio
async def test_non_backup_job_due_uses_persisted_last_run(test_db):
    del test_db

    job = scheduler._ScheduledJob("maintenance", lambda: 3600, AsyncMock())
    db.upsert_scheduler_state("maintenance", last_run_at="2026-04-22 10:00:00")

    assert scheduler._job_due(job, db._parse_datetime("2026-04-22 10:30:00")) is False
    assert scheduler._job_due(job, db._parse_datetime("2026-04-22 11:00:00")) is True


@pytest.mark.anyio
async def test_backup_job_due_uses_latest_backup_snapshot_not_scheduler_state(test_db):
    del test_db

    job = scheduler._ScheduledJob("backup", lambda: 3600, AsyncMock())
    db.upsert_scheduler_state("backup", last_run_at="2026-04-20 08:00:00")

    with patch(
        "services.scheduler.backup_service.get_latest_backup_datetime",
        return_value=db._parse_datetime("2026-04-22 10:00:00"),
    ):
        assert scheduler._job_due(job, db._parse_datetime("2026-04-22 10:30:00")) is False
        assert scheduler._job_due(job, db._parse_datetime("2026-04-22 11:00:00")) is True


@pytest.mark.anyio
async def test_start_is_idempotent_for_review_and_shared_tasks(test_db):
    del test_db

    fake_bot = MagicMock()
    fake_bot.is_closed.return_value = True
    fake_bot.wait_until_ready = AsyncMock()

    with patch("services.scheduler.asyncio.get_running_loop") as get_loop:
        loop = MagicMock()
        shared_task = MagicMock(done=MagicMock(return_value=False))
        review_task = MagicMock(done=MagicMock(return_value=False))

        def _fake_create_task(coro, *, name=None):
            del name
            coro.close()
            if loop.create_task.call_count == 0:
                return review_task
            return shared_task

        loop.create_task.side_effect = _fake_create_task
        get_loop.return_value = loop

        scheduler.stop()
        scheduler.start(fake_bot, 123, owner_label="bot")
        scheduler.start(fake_bot, 123, owner_label="bot")

    assert loop.create_task.call_count == 2
    scheduler.stop()
