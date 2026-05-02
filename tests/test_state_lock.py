import db.chat
import pytest

from services import state


@pytest.fixture(autouse=True)
def _release_pipeline_lock_after_test(test_db):
    if state.PIPELINE_LOCK.locked():
        state.PIPELINE_LOCK.release()
    db.chat.set_session(state.PIPELINE_LEASE_KEY, None, user_id=state.PIPELINE_LEASE_SCOPE)
    yield
    if state.PIPELINE_LOCK.locked():
        state.PIPELINE_LOCK.release()
    db.chat.set_session(state.PIPELINE_LEASE_KEY, None, user_id=state.PIPELINE_LEASE_SCOPE)


@pytest.mark.anyio
async def test_pipeline_serialized_releases_lock_on_exception():
    assert not state.PIPELINE_LOCK.locked()
    assert db.chat.get_session_lease(state.PIPELINE_LEASE_KEY, user_id=state.PIPELINE_LEASE_SCOPE) is None

    with pytest.raises(RuntimeError):
        async with state.pipeline_serialized(poll_interval=0):
            assert state.PIPELINE_LOCK.locked()
            assert (
                db.chat.get_session_lease(
                    state.PIPELINE_LEASE_KEY, user_id=state.PIPELINE_LEASE_SCOPE
                )
                is not None
            )
            raise RuntimeError("boom")

    assert not state.PIPELINE_LOCK.locked()
    assert db.chat.get_session_lease(state.PIPELINE_LEASE_KEY, user_id=state.PIPELINE_LEASE_SCOPE) is None


def test_pipeline_serialized_nowait_reports_busy_without_releasing_foreign_lock():
    with state.pipeline_serialized_nowait() as acquired:
        assert acquired is True
        assert state.PIPELINE_LOCK.locked()

        with state.pipeline_serialized_nowait() as nested_acquired:
            assert nested_acquired is False
            lease = db.chat.get_session_lease(
                state.PIPELINE_LEASE_KEY, user_id=state.PIPELINE_LEASE_SCOPE
            )
            assert lease is not None
            assert state.PIPELINE_LOCK.locked()

    assert not state.PIPELINE_LOCK.locked()
    assert db.chat.get_session_lease(state.PIPELINE_LEASE_KEY, user_id=state.PIPELINE_LEASE_SCOPE) is None


def test_pipeline_serialized_nowait_rejects_busy_durable_lease():
    assert db.chat.try_acquire_session_lease(
        state.PIPELINE_LEASE_KEY,
        owner_token="foreign-owner",
        lease_seconds=state.PIPELINE_LEASE_SECONDS,
        user_id=state.PIPELINE_LEASE_SCOPE,
    )

    with state.pipeline_serialized_nowait() as acquired:
        assert acquired is False
        assert not state.PIPELINE_LOCK.locked()

    assert not state.PIPELINE_LOCK.locked()
    lease = db.chat.get_session_lease(state.PIPELINE_LEASE_KEY, user_id=state.PIPELINE_LEASE_SCOPE)
    assert lease is not None
    assert lease["owner_token"] == "foreign-owner"
