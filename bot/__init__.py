"""Discord bot package for the Learning Agent.

Importing this package creates the ``bot`` instance and registers all
commands and event handlers as a side-effect.
"""

from bot.app import bot  # noqa: F401 — re-export; also triggers submodule imports

# Import submodules to register @bot.hybrid_command and @bot.event decorators
from bot import commands  # noqa: F401
from bot import events    # noqa: F401

__all__ = ["bot"]
