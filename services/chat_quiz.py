import db


def _button(label: str, action: dict, style: str = "secondary") -> dict:
    return {
        "label": label,
        "style": style,
        "action": action,
    }


def _button_group(buttons: list[dict], title: str | None = None) -> list[dict]:
    if not buttons:
        return []
    group = {"type": "button_group", "buttons": buttons}
    if title:
        group["title"] = title
    return [group]


def _multiple_choice_block(choices: list[str]) -> list[dict]:
    normalized = [str(choice).strip() for choice in choices if str(choice).strip()]
    if not normalized:
        return []
    return [
        {
            "type": "multiple_choice",
            "title": "Choose an answer",
            "choices": [
                {
                    "label": choice,
                    "action": {"kind": "send_message", "message": f"I choose: {choice}"},
                }
                for choice in normalized
            ],
        }
    ]


def _quiz_again_prompt(concept_id: int, title: str) -> str:
    return f"[BUTTON] Quiz me again on concept #{concept_id} ({title})"


def _quiz_explain_prompt(concept_id: int, title: str) -> str:
    return (
        f"[BUTTON] Explain concept #{concept_id} ({title}) in detail "
        f"— I got the quiz wrong and need help understanding it"
    )


def build_quiz_question_actions(
    concept_id: int | None,
    choices: list[str] | None = None,
) -> list[dict]:
    actions = _multiple_choice_block(choices or [])
    if concept_id is None:
        return actions
    concept = db.get_concept(int(concept_id))
    if not concept or concept.get("review_count", 0) < 2:
        return actions
    actions.extend(
        _button_group(
            [
                _button(
                    "I know this",
                    {"kind": "skip_quiz", "concept_id": int(concept_id)},
                    style="secondary",
                )
            ],
            title="Quiz actions",
        )
    )
    return actions


def build_quiz_navigation_actions(concept_id: int | None, quality: int | None) -> list[dict]:
    if concept_id is None or quality is None:
        return []
    concept = db.get_concept(int(concept_id))
    title = concept["title"] if concept else f"#{concept_id}"

    buttons = []
    if quality >= 3:
        buttons.append(
            _button(
                "Next due",
                {"kind": "send_message", "message": "[BUTTON] Quiz me on the next due concept"},
                style="primary",
            )
        )
        buttons.append(
            _button(
                "Quiz again",
                {"kind": "send_message", "message": _quiz_again_prompt(int(concept_id), title)},
            )
        )
    else:
        buttons.append(
            _button(
                "Explain",
                {"kind": "send_message", "message": _quiz_explain_prompt(int(concept_id), title)},
                style="primary",
            )
        )
        buttons.append(
            _button(
                "Quiz again",
                {"kind": "send_message", "message": _quiz_again_prompt(int(concept_id), title)},
            )
        )
        buttons.append(
            _button(
                "Next due",
                {"kind": "send_message", "message": "[BUTTON] Quiz me on the next due concept"},
            )
        )

    buttons.append(_button("Done", {"kind": "dismiss"}))
    return _button_group(buttons, title="Quiz follow-up")


def derive_quiz_actions(action_data: dict | None, reply: str) -> list[dict]:
    if not action_data or "⚠️" in (reply or ""):
        return []

    action_name = action_data.get("action", "").lower().strip()
    params = action_data.get("params", {})

    if action_name == "quiz":
        return build_quiz_question_actions(params.get("concept_id"), params.get("choices"))

    if action_name == "assess":
        concept_id = db.get_session("last_assess_concept_id") or params.get("concept_id")
        quality = db.get_session("last_assess_quality") or params.get("quality")
        try:
            concept_id = int(concept_id) if concept_id is not None else None
        except (TypeError, ValueError):
            concept_id = None
        try:
            quality = int(quality) if quality is not None else None
        except (TypeError, ValueError):
            quality = None
        return build_quiz_navigation_actions(concept_id, quality)

    return []