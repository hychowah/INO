"""Core message handler and DB initialization helpers."""

import logging
from datetime import datetime

import discord

import db
from services import pipeline, state
from services.learn_turn import run_learn_turn
from services.parser import parse_llm_response

logger = logging.getLogger("bot")

# Maps message_id → (action_data, View) for add_concept and suggest_topic
_pending_confirmations: dict[int, tuple[dict, discord.ui.View]] = {}

_AFFIRMATIVES = {
    "yes",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "y",
    "add",
    "add it",
    "go ahead",
    "do it",
    "please",
    "yea",
}
_NEGATIVES = {"no", "nah", "nope", "skip", "n", "no thanks", "pass", "decline", "don't", "dont"}


def _is_affirmative(text: str) -> bool:
    text = text.lower().strip().rstrip(".!,")
    return text in _AFFIRMATIVES or text.startswith(("yes", "sure", "add"))


def _is_negative(text: str) -> bool:
    text = text.lower().strip().rstrip(".!,")
    return text in _NEGATIVES or text.startswith(("no ", "nah", "skip"))


_db_initialized = False


def _ensure_db():
    """Ensure DB is initialized (idempotent)."""
    global _db_initialized
    if not _db_initialized:
        pipeline.init_databases()
        _db_initialized = True


async def _handle_user_message(
    text: str, author: str, *, user_id: str | None = None
) -> tuple[str, dict | None, dict | None, dict | None]:
    """Core handler: text in → (response, pending_action | None, assess_meta | None,
    quiz_meta | None)."""
    active_user = user_id or author
    with state.current_user_scope(active_user):
        async with state.pipeline_serialized():
            _ensure_db()
            state.begin_interactive_turn()

            result = await run_learn_turn(
                text,
                author,
                source="discord",
                call_with_fetch_loop=pipeline.call_with_fetch_loop,
                parse_response=parse_llm_response,
                execute_response=pipeline.execute_llm_response,
                process_output=pipeline.process_output,
                on_pending_intercept=lambda display_msg: _record_pending_confirmation(text, display_msg),
            )

            if result.pending_action:
                action_name = result.pending_action.get("action", "").lower().strip()
                logger.info(f"Intercepted {action_name} — pending user confirmation")
                return result.message, result.pending_action, None, None

            logger.info(f"Completed: '{text[:50]}' → {result.msg_type}")
            return result.message, None, result.assess_meta, result.quiz_meta


def _record_pending_confirmation(text: str, display_msg: str) -> None:
    if text:
        db.add_chat_message("user", text)
    if display_msg:
        db.add_chat_message("assistant", display_msg)
