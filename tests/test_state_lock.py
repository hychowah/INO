import pytest

from services import state


@pytest.fixture(autouse=True)
def _release_pipeline_lock_after_test():
    if state.PIPELINE_LOCK.locked():
        state.PIPELINE_LOCK.release()
    yield
    if state.PIPELINE_LOCK.locked():
        state.PIPELINE_LOCK.release()


@pytest.mark.anyio
async def test_pipeline_serialized_releases_lock_on_exception():
    assert not state.PIPELINE_LOCK.locked()

    with pytest.raises(RuntimeError):
        async with state.pipeline_serialized(poll_interval=0):
            assert state.PIPELINE_LOCK.locked()
            raise RuntimeError("boom")

    assert not state.PIPELINE_LOCK.locked()


def test_pipeline_serialized_nowait_reports_busy_without_releasing_foreign_lock():
    state.PIPELINE_LOCK.acquire()

    with state.pipeline_serialized_nowait() as acquired:
        assert acquired is False
        assert state.PIPELINE_LOCK.locked()

    assert state.PIPELINE_LOCK.locked()
    state.PIPELINE_LOCK.release()
