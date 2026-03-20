"""
User preferences — persona selection and related settings.

Uses the session_state table in chat_history.db for storage.
No new migration needed — session_state already exists.
"""

from pathlib import Path

import config
from db.chat import get_session, set_session

# Where persona preset .md files live
PERSONAS_DIR = config.PERSONAS_DIR
DEFAULT_PERSONA = "mentor"


def get_available_personas() -> list[str]:
    """Return sorted list of available persona preset names (without .md extension)."""
    if not PERSONAS_DIR.exists():
        return [DEFAULT_PERSONA]
    names = sorted(p.stem for p in PERSONAS_DIR.glob("*.md"))
    return names if names else [DEFAULT_PERSONA]


def get_persona() -> str:
    """Get the active persona name. Falls back to DEFAULT_PERSONA."""
    stored = get_session("persona")
    if stored and stored in get_available_personas():
        return stored
    return DEFAULT_PERSONA


def set_persona(name: str) -> None:
    """Set the active persona. Raises ValueError if preset doesn't exist."""
    available = get_available_personas()
    if name not in available:
        raise ValueError(
            f"Unknown persona {name!r}. Available: {', '.join(available)}"
        )
    set_session("persona", name)


def get_persona_content(name: str | None = None) -> str:
    """Read and return the markdown content of a persona file.
    Falls back to DEFAULT_PERSONA if the file is missing."""
    if name is None:
        name = get_persona()
    path = PERSONAS_DIR / f"{name}.md"
    if not path.exists():
        path = PERSONAS_DIR / f"{DEFAULT_PERSONA}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
