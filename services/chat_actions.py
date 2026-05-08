"""Shared chat action helpers for API and chat confirmation flows."""

import db

from services import state
from services.tools import execute_action, set_action_source

INTERCEPTED_ACTIONS = frozenset({"add_concept", "suggest_topic"})
LIGHTWEIGHT_CONFIRMABLE_ACTIONS = frozenset({"add_concept", "suggest_topic"})
API_CONFIRMABLE_ACTIONS = frozenset({"add_concept", "suggest_topic", "add_topic", "link_concept"})
CHAT_CONFIRMABLE_ACTIONS = frozenset(
    {
        "add_concept",
        "suggest_topic",
        "preference_update",
        "maintenance_review",
        "taxonomy_review",
    }
)


def execute_lightweight_confirm(action_data: dict, *, source: str) -> tuple[bool, str]:
    action = require_confirmable_action(
        action_data,
        LIGHTWEIGHT_CONFIRMABLE_ACTIONS,
        "confirmed here",
    )
    set_action_source(source)

    if action == "suggest_topic":
        from services.tools_assess import execute_suggest_topic_accept

        success, summary, _topic_id = execute_suggest_topic_accept(action_data)
        if not success:
            return False, f"⚠️ {summary}"
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", summary)
        return True, summary

    msg_type, result = execute_action(action, action_data.get("params", {}))
    if msg_type == "error":
        return False, f"⚠️ Could not add concept: {result}"
    success_message = f"✅ {result}"
    db.add_chat_message("user", confirmation_history_entry(action_data))
    db.add_chat_message("assistant", success_message)
    return True, success_message


def execute_lightweight_decline(action_data: dict) -> None:
    require_confirmable_action(
        action_data,
        LIGHTWEIGHT_CONFIRMABLE_ACTIONS,
        "declined here",
    )
    db.add_chat_message("user", decline_history_entry(action_data))


async def resolve_lightweight_confirmation(
    action_data: dict,
    *,
    approve: bool,
    user_id: str,
    source: str = "discord",
) -> str | None:
    """Execute a Discord lightweight confirm or decline inside the canonical user scope."""
    with state.current_user_scope(user_id):
        async with state.pipeline_serialized():
            if approve:
                _success, display_note = execute_lightweight_confirm(action_data, source=source)
                return display_note
            execute_lightweight_decline(action_data)
            return None


def normalize_action(action_data: dict | str | None) -> str:
    if isinstance(action_data, dict):
        value = action_data.get("action", "")
    else:
        value = action_data or ""
    return str(value).lower().strip()


def is_intercepted_action(action_data: dict | str | None) -> bool:
    return normalize_action(action_data) in INTERCEPTED_ACTIONS


def require_confirmable_action(
    action_data: dict, allowed_actions: frozenset[str], target: str
) -> str:
    action = normalize_action(action_data)
    if not action:
        raise ValueError("Missing 'action' in action_data")
    if action not in allowed_actions:
        raise ValueError(f"Action '{action}' cannot be {target}")
    return action


def confirmation_history_entry(action_data: dict) -> str:
    return _history_entry(action_data, decision="confirmed")


def decline_history_entry(action_data: dict) -> str:
    return _history_entry(action_data, decision="declined")


def _history_entry(action_data: dict, decision: str) -> str:
    action = normalize_action(action_data)
    params = action_data.get("params", {}) if isinstance(action_data, dict) else {}

    if action == "add_concept":
        label = "add concept"
    elif action in {"suggest_topic", "add_topic"}:
        title = params.get("title", "topic")
        label = f'add topic "{title}"'
    elif action == "link_concept":
        label = "link concept"
    elif action == "preference_update":
        label = "preference update"
    elif action == "maintenance_review":
        label = "maintenance changes"
    elif action == "taxonomy_review":
        label = "taxonomy changes"
    else:
        raise ValueError(f"Action '{action}' has no history marker")

    return f"[{decision}: {label}]"
