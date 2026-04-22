import db


def test_upsert_scheduler_state_round_trips_fields(test_db):
    del test_db

    db.upsert_scheduler_state(
        "backup",
        last_run_at="2026-04-20 09:00:00",
        last_success_at="2026-04-20 09:00:01",
        last_error=None,
    )

    row = db.get_scheduler_state("backup")

    assert row is not None
    assert row["job_name"] == "backup"
    assert row["last_run_at"] == "2026-04-20 09:00:00"
    assert row["last_success_at"] == "2026-04-20 09:00:01"
    assert row["last_error"] is None
    assert row["updated_at"]


def test_upsert_scheduler_state_overwrites_existing_row(test_db):
    del test_db

    db.upsert_scheduler_state(
        "backup",
        last_run_at="2026-04-20 09:00:00",
        last_success_at="2026-04-20 09:00:01",
    )
    db.upsert_scheduler_state(
        "backup",
        last_run_at="2026-04-21 10:00:00",
        last_success_at=None,
        last_error="disk full",
    )

    row = db.get_scheduler_state("backup")

    assert row is not None
    assert row["last_run_at"] == "2026-04-21 10:00:00"
    assert row["last_success_at"] is None
    assert row["last_error"] == "disk full"


def test_acquire_scheduler_owner_blocks_live_owner(test_db):
    del test_db

    now = "2026-04-22 10:00:00"
    acquired = db.acquire_scheduler_owner(1001, "bot", stale_seconds=180, now=now)
    blocked = db.acquire_scheduler_owner(2002, "api", stale_seconds=180, now=now)

    owner = db.get_scheduler_owner()

    assert acquired is True
    assert blocked is False
    assert owner is not None
    assert owner["owner_pid"] == 1001
    assert owner["owner_label"] == "bot"


def test_acquire_scheduler_owner_takes_over_stale_lock(test_db):
    del test_db

    first_now = "2026-04-22 10:00:00"
    second_now = "2026-04-22 10:05:00"

    assert db.acquire_scheduler_owner(1001, "bot", stale_seconds=180, now=first_now) is True
    assert db.acquire_scheduler_owner(2002, "api", stale_seconds=180, now=second_now) is True

    owner = db.get_scheduler_owner()

    assert owner is not None
    assert owner["owner_pid"] == 2002
    assert owner["owner_label"] == "api"
    assert owner["heartbeat_at"] == second_now


def test_heartbeat_and_release_require_matching_owner(test_db):
    del test_db

    first_now = "2026-04-22 10:00:00"
    second_now = "2026-04-22 10:01:00"
    assert db.acquire_scheduler_owner(1001, "bot", stale_seconds=180, now=first_now) is True

    assert db.heartbeat_scheduler_owner(2002, now=second_now) is False
    assert db.heartbeat_scheduler_owner(1001, now=second_now) is True
    assert db.release_scheduler_owner(2002) is False
    assert db.release_scheduler_owner(1001) is True
    assert db.get_scheduler_owner() is None


def test_get_scheduler_states_returns_all_jobs(test_db):
    del test_db

    db.upsert_scheduler_state("backup", last_run_at="2026-04-20 09:00:00")
    db.upsert_scheduler_state("maintenance", last_run_at="2026-04-20 10:00:00")

    states = db.get_scheduler_states()

    assert set(states) == {"backup", "maintenance"}
    assert states["backup"]["last_run_at"] == "2026-04-20 09:00:00"
    assert states["maintenance"]["last_run_at"] == "2026-04-20 10:00:00"
