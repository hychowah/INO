"""
Process-wide runtime coordination state shared across entry points.

This module owns lightweight shared state that must be visible across the bot,
scheduler, and embedded WebUI server without introducing import cycles.
"""

import asyncio
import contextvars
import functools
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime

# Tracks the authorized user's last message time.
# Updated by bot.py, read by scheduler.py for activity suppression.
last_activity_at: datetime | None = None

# Serializes access to the chat pipeline while process-global session state is
# still shared between the bot, scheduler, and embedded WebUI server.
PIPELINE_LOCK = threading.Lock()

# ============================================================================
# Current user identity (ContextVar — set at entry points, read by db layer)
# ============================================================================

_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_user_id", default="default"
)


def set_current_user(user_id: str) -> None:
    """Set the active user for the current context (call at entry points)."""
    _current_user_id.set(user_id)


def get_current_user() -> str:
    """Get the active user_id for the current context."""
    return _current_user_id.get()


@asynccontextmanager
async def pipeline_serialized(poll_interval: float = 0.05):
    """Serialize async callers against the shared pipeline lock.

    The lock is polled with ``blocking=False`` so task cancellation cannot strand
    a worker thread waiting in ``lock.acquire()``.
    """
    while not PIPELINE_LOCK.acquire(blocking=False):
        await asyncio.sleep(poll_interval)
    try:
        yield
    finally:
        PIPELINE_LOCK.release()


def serialized_pipeline(func):
    """Decorator form of ``pipeline_serialized`` for async entry points."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with pipeline_serialized():
            return await func(*args, **kwargs)

    return wrapper


@contextmanager
def pipeline_serialized_nowait():
    """Try to acquire the shared pipeline lock without waiting."""
    acquired = PIPELINE_LOCK.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            PIPELINE_LOCK.release()
