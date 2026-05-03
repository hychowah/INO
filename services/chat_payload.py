from services.parser import guard_user_message


def build_chat_payload(
    message: str,
    *,
    msg_type: str = "reply",
    pending_action: dict | None = None,
    actions: list[dict] | None = None,
    clear_history: bool = False,
) -> dict:
    payload = {
        "type": msg_type,
        "message": guard_user_message(message),
        "pending_action": pending_action,
    }
    if actions:
        payload["actions"] = actions
    if clear_history:
        payload["clear_history"] = True
    return payload