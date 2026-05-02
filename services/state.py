"""
Process-wide runtime coordination state shared across entry points.

This module owns lightweight shared state that must be visible across the bot,
scheduler, and FastAPI chat entry points without introducing import cycles.
"""

import asyncio
import contextvars
import functools
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime

import config

# Tracks the authorized user's last message time.
# Updated by bot.py, read by scheduler.py for activity suppression.
last_activity_at: datetime | None = None
ACTIVITY_HEARTBEAT_KEY = "user_activity_heartbeat"

# Serializes access to the chat pipeline while process-global session state is
# still shared between concurrent tasks in the same process. A durable lease in
# session_state is the authoritative cross-process guard.
PIPELINE_LOCK = threading.Lock()
PIPELINE_LEASE_KEY = "pipeline_turn_lease"
PIPELINE_LEASE_SCOPE = "__runtime__"
PIPELINE_LEASE_SECONDS = 300

# ============================================================================
# Current user identity (ContextVar — set at entry points, read by db layer)
# ============================================================================

_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user_id", default="default"
)


def set_current_user(user_id: str) -> None:
    """Set the active user for the current context (call at entry points)."""
    _current_user_id.set(user_id)


@contextmanager
def current_user_scope(user_id: str):
    """Temporarily bind the active user for the current task/context."""
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def get_current_user() -> str:
    """Get the active user_id for the current context."""
    return _current_user_id.get()


def get_local_user_id() -> str:
    """Return the configured canonical user id for local-first single-user flows."""
    candidate = (getattr(config, "LOCAL_USER_ID", "") or "").strip()
    return candidate or "default"


def begin_interactive_turn(*, reset_quiz_answered: bool = True) -> datetime:
    """Apply the shared preamble for an interactive user turn."""
    activity_at = mark_user_activity()
    if reset_quiz_answered:
        import db

        db.set_session("quiz_answered", None)
    return activity_at


def mark_user_activity(at: datetime | None = None) -> datetime:
    """Record recent user activity in both runtime memory and session state."""
    global last_activity_at

    activity_at = at or datetime.now()
    last_activity_at = activity_at

    import db

    db.set_session(ACTIVITY_HEARTBEAT_KEY, "1")
    return activity_at


def get_last_user_activity() -> datetime | None:
    """Return the freshest activity timestamp from memory or durable session state."""
    candidates: list[datetime] = []
    if last_activity_at is not None:
        candidates.append(last_activity_at)

    import db

    updated_at = db.get_session_updated_at(ACTIVITY_HEARTBEAT_KEY)
    if updated_at:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed_utc = datetime.strptime(updated_at, fmt).replace(tzinfo=UTC)
                candidates.append(parsed_utc.astimezone().replace(tzinfo=None))
                break
            except ValueError:
                continue

    if not candidates:
        return None
    return max(candidates)


def _try_acquire_pipeline_lease(owner_token: str) -> bool:
    import db.chat as db_chat

    return db_chat.try_acquire_session_lease(
        PIPELINE_LEASE_KEY,
        owner_token,
        PIPELINE_LEASE_SECONDS,
        user_id=PIPELINE_LEASE_SCOPE,
    )


def _release_pipeline_lease(owner_token: str) -> bool:
    import db.chat as db_chat

    return db_chat.release_session_lease(
        PIPELINE_LEASE_KEY,
        owner_token,
        user_id=PIPELINE_LEASE_SCOPE,
    )


@asynccontextmanager
async def pipeline_serialized(poll_interval: float = 0.05):
    """Serialize async callers against a durable lease plus local mutex.

    The durable lease prevents overlapping turns across processes. The local
    mutex preserves the existing same-process safety and keeps the public lock
    surface stable for callers that only care about in-process coordination.
    """
    owner_token = uuid.uuid4().hex

    while not _try_acquire_pipeline_lease(owner_token):
        await asyncio.sleep(poll_interval)

    acquired_local = False
    try:
        while not PIPELINE_LOCK.acquire(blocking=False):
            await asyncio.sleep(poll_interval)
        acquired_local = True
        yield
    finally:
        if acquired_local:
            PIPELINE_LOCK.release()
        _release_pipeline_lease(owner_token)


def serialized_pipeline(func):
    """Decorator form of ``pipeline_serialized`` for async entry points."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with pipeline_serialized():
            return await func(*args, **kwargs)

    return wrapper


@contextmanager
def pipeline_serialized_nowait():
    """Try to acquire the shared pipeline turn without waiting."""
    owner_token = uuid.uuid4().hex
    acquired = _try_acquire_pipeline_lease(owner_token)
    acquired_local = False

    if acquired:
        acquired_local = PIPELINE_LOCK.acquire(blocking=False)
        if not acquired_local:
            _release_pipeline_lease(owner_token)
            acquired = False

    try:
        yield acquired
    finally:
        if acquired_local:
            PIPELINE_LOCK.release()
        if acquired:
            _release_pipeline_lease(owner_token)
