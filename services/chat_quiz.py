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


def build_quiz_followup_prompt(kind: str, concept_id: int | None = None) -> str:
    normalized = str(kind).lower().strip()
    if normalized == "next_due":
        return "[BUTTON] Quiz me on the next due concept"

    if concept_id is None:
        raise ValueError(f"quiz follow-up '{normalized}' requires concept_id")

    concept = db.get_concept(int(concept_id))
    title = concept["title"] if concept else f"#{concept_id}"

    if normalized == "quiz_again":
        return _quiz_again_prompt(int(concept_id), title)
    if normalized == "explain":
        return _quiz_explain_prompt(int(concept_id), title)
    raise ValueError(f"Unknown quiz follow-up '{normalized}'")


def derive_discord_quiz_delivery(actions: list[dict] | None) -> tuple[dict | None, dict | None]:
    """Map shared chat action blocks back to the Discord quiz view metadata contract."""
    if not actions:
        return None, None

    for block in actions:
        if str(block.get("type", "")).lower().strip() != "button_group":
            continue
        for button in block.get("buttons", []):
            action = button.get("action", {})
            kind = str(action.get("kind", "")).lower().strip()
            if kind == "skip_quiz" and action.get("concept_id") is not None:
                return None, {
                    "concept_id": int(action["concept_id"]),
                    "show_skip": True,
                }

        followups = [
            button.get("action", {})
            for button in block.get("buttons", [])
            if str(button.get("action", {}).get("kind", "")).lower().strip() == "quiz_followup"
        ]
        if not followups:
            continue

        concept_id = next(
            (
                int(action["concept_id"])
                for action in followups
                if action.get("concept_id") is not None
            ),
            None,
        )
        quality = 2 if any(action.get("followup") == "explain" for action in followups) else 5
        if concept_id is not None:
            return {"concept_id": concept_id, "quality": quality}, None

    return None, None


def execute_skip_quiz_action(concept_id: int, *, user_id: str, source: str) -> dict:
    from services.tools_assess import skip_quiz

    result = skip_quiz(int(concept_id), user_id=user_id, source=source)
    if "error" in result:
        return {"error": result["error"]}

    message = (
        f"⏭️ Skipped — score: {result['old_score']}→{result['new_score']}, "
        f"next review in {result['interval_days']}d"
    )
    return {
        "message": message,
        "concept_id": result["concept_id"],
        "quality": 5,
        "actions": build_quiz_navigation_actions(result["concept_id"], 5),
    }


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

    buttons = []
    if quality >= 3:
        buttons.append(
            _button(
                "Next due",
                {"kind": "quiz_followup", "followup": "next_due"},
                style="primary",
            )
        )
        buttons.append(
            _button(
                "Quiz again",
                {"kind": "quiz_followup", "followup": "quiz_again", "concept_id": int(concept_id)},
            )
        )
    else:
        buttons.append(
            _button(
                "Explain",
                {"kind": "quiz_followup", "followup": "explain", "concept_id": int(concept_id)},
                style="primary",
            )
        )
        buttons.append(
            _button(
                "Quiz again",
                {"kind": "quiz_followup", "followup": "quiz_again", "concept_id": int(concept_id)},
            )
        )
        buttons.append(
            _button(
                "Next due",
                {"kind": "quiz_followup", "followup": "next_due"},
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