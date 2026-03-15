"""
Shared state between bot and scheduler.
Eliminates the circular dependency where scheduler imports bot at runtime.
"""

from datetime import datetime

# Tracks the authorized user's last message time.
# Updated by bot.py, read by scheduler.py for activity suppression.
last_activity_at: datetime | None = None
