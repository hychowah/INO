"""
Shared state between bot and scheduler.
Eliminates the circular dependency where scheduler imports bot at runtime.
"""

import contextvars
from datetime import datetime

# Tracks the authorized user's last message time.
# Updated by bot.py, read by scheduler.py for activity suppression.
last_activity_at: datetime | None = None

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
