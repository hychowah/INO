"""
Repair sub-agent — fixes malformed LLM action JSON via ephemeral LLM session.
See DEVNOTES.md §2.2 for background.
"""

import json
import logging
from datetime import datetime

from services import tools
from services.parser import _extract_json_object
from services.llm import get_provider, LLMError

logger = logging.getLogger("repair")

# Session state
_repair_session_name: str | None = None
_repair_session_created_at: datetime | None = None
_repair_session_seeded: bool = False
REPAIR_SESSION_TTL_MINUTES = 15


def _get_repair_session() -> str:
    """Return a repair session name, rotating every REPAIR_SESSION_TTL_MINUTES."""
    global _repair_session_name, _repair_session_created_at, _repair_session_seeded
    now = datetime.now()
    if (_repair_session_name is None or _repair_session_created_at is None
            or (now - _repair_session_created_at).total_seconds()
            > REPAIR_SESSION_TTL_MINUTES * 60):
        _repair_session_name = f"learn_repair_{now.strftime('%H%M')}"
        _repair_session_created_at = now
        _repair_session_seeded = False
        logger.info(f"New repair session: {_repair_session_name}")
    return _repair_session_name


async def repair_action(action_data: dict) -> dict | None:
    """Call LLM via a lightweight session to fix a malformed action JSON.
    Returns the corrected dict, or None if repair fails."""
    provider = get_provider()
    global _repair_session_seeded

    session = _get_repair_session()
    valid_actions = ", ".join(sorted(tools.ACTION_HANDLERS.keys()))
    malformed = json.dumps(action_data, default=str)

    if not _repair_session_seeded:
        prompt = (
            f"You are a JSON repair tool for a learning agent. Valid action names are:\n"
            f"{valid_actions}\n\n"
            f"When given malformed JSON, return ONLY the corrected JSON with:\n"
            f"- action name fixed to the closest valid action from the list above\n"
            f"- params wrapped in a \"params\" object if at top level\n"
            f"- \"message\" field preserved\n"
            f"No explanation, just the JSON.\n\n"
            f"Fix this: {malformed}"
        )
        _repair_session_seeded = True
    else:
        prompt = f"Fix this: {malformed}"

    logger.info(f"Repair sub-agent fired for action '{action_data.get('action')}' "
                f"(session={session}, prompt={len(prompt)} chars)")

    try:
        raw = await provider.send(
            prompt,
            session=session,
            system_prompt=None,
            timeout=30,
        )

        if not raw:
            logger.warning("Repair sub-agent returned empty output")
            return None

        obj = _extract_json_object(raw)
        if obj and obj.get("action", "").lower().strip() in tools.ACTION_HANDLERS:
            repaired_action = obj["action"].lower().strip()
            original_action = action_data.get("action", "")
            logger.info(f"Repair succeeded: '{original_action}' → '{repaired_action}'")
            return obj
        else:
            logger.warning(f"Repair sub-agent output not valid: {raw[:200]}")
            return None
    except LLMError as e:
        logger.error(f"Repair sub-agent LLM error: {e}")
        return None
    except Exception as e:
        logger.error(f"Repair sub-agent error: {e}")
        return None
