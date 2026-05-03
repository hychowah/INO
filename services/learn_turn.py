from dataclasses import dataclass
import logging
from typing import Awaitable, Callable

import db
from services.chat_actions import is_intercepted_action
from services.chat_payload import build_chat_payload
from services.tools import set_action_source

logger = logging.getLogger("learn_turn")


@dataclass(frozen=True)
class LearnTurnResult:
    message: str
    msg_type: str
    pending_action: dict | None
    action_data: dict | None
    assess_meta: dict | None = None
    quiz_meta: dict | None = None

    def to_discord_result(self) -> tuple[str, dict | None, dict | None, dict | None]:
        return self.message, self.pending_action, self.assess_meta, self.quiz_meta

    def to_chat_payload(
        self,
        *,
        actions: list[dict] | None = None,
    ) -> dict:
        return build_chat_payload(
            self.message,
            msg_type=self.msg_type,
            pending_action=self.pending_action,
            actions=actions if not self.pending_action else None,
        )


def _resolve_turn_mode() -> str:
    if db.get_session("active_concept_ids"):
        return "reply"
    if db.get_session("quiz_anchor_concept_id"):
        return "reply"

    from services.review_state import get_pending_review

    if get_pending_review():
        return "reply"

    return "command"


async def run_learn_turn(
    text: str,
    author: str,
    *,
    source: str,
    call_with_fetch_loop: Callable[[str, str, str], Awaitable[str]],
    parse_response: Callable[[str], tuple[str, str, dict | None]],
    execute_response: Callable[[str, str, str], Awaitable[str]],
    process_output: Callable[[str], tuple[str, str]],
    on_pending_intercept: Callable[[str], None] | None = None,
) -> LearnTurnResult:
    set_action_source(source)
    mode = _resolve_turn_mode()
    logger.info("learn turn mode=%s active_quiz=%s", mode, mode == "reply")

    llm_response = await call_with_fetch_loop(mode, text, author)
    _prefix, message, action_data = parse_response(llm_response)

    if action_data and is_intercepted_action(action_data) and not text.startswith("[BUTTON]"):
        display_msg = action_data.get("message", message or "")
        if on_pending_intercept is not None:
            on_pending_intercept(display_msg)
        return LearnTurnResult(
            message=display_msg,
            msg_type="pending_confirm",
            pending_action=action_data,
            action_data=action_data,
        )

    final_result = await execute_response(text, llm_response, mode)
    msg_type, reply = process_output(final_result)

    assess_meta = None
    if action_data and action_data.get("action", "").lower().strip() == "assess" and "⚠️" not in (reply or ""):
        concept_id = db.get_session("last_assess_concept_id")
        quality = db.get_session("last_assess_quality")
        if concept_id and quality:
            assess_meta = {
                "concept_id": int(concept_id),
                "quality": int(quality),
            }

    quiz_meta = None
    if (
        action_data
        and action_data.get("action", "").lower().strip() == "quiz"
        and action_data.get("params", {}).get("concept_id") is not None
    ):
        quiz_concept_id = int(action_data["params"]["concept_id"])
        quiz_concept = db.get_concept(quiz_concept_id)
        quiz_meta = {
            "concept_id": quiz_concept_id,
            "show_skip": (quiz_concept.get("review_count", 0) >= 2) if quiz_concept else False,
        }

    return LearnTurnResult(
        message=reply,
        msg_type=msg_type,
        pending_action=None,
        action_data=action_data,
        assess_meta=assess_meta,
        quiz_meta=quiz_meta,
    )