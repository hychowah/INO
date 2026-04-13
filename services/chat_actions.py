"""Shared chat action helpers for API and chat confirmation flows."""

INTERCEPTED_ACTIONS = frozenset({"add_concept", "suggest_topic"})
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

WEBUI_CONFIRMABLE_ACTIONS = CHAT_CONFIRMABLE_ACTIONS


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
