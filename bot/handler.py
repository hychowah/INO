"""Core message handler and DB initialization helpers."""

import logging
from datetime import datetime

import discord

import db
from services import pipeline, state
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
    text: str, author: str
) -> tuple[str, dict | None, dict | None, dict | None]:
    """Core handler: text in → (response, pending_action | None, assess_meta | None,
    quiz_meta | None)."""
    async with state.pipeline_serialized():
        _ensure_db()
        state.mark_user_activity()

        # Reset race guard — new message means new quiz cycle
        db.set_session("quiz_answered", None)

        from services.tools import set_action_source

        set_action_source("discord")

        llm_response = await pipeline.call_with_fetch_loop("command", text, author)

        prefix, message, action_data = parse_llm_response(llm_response)
        if (
            action_data
            and action_data.get("action", "").lower().strip() in ("add_concept", "suggest_topic")
            and not text.startswith("[BUTTON]")
        ):
            if text:
                db.add_chat_message("user", text)
            display_msg = action_data.get("message", message or "")
            if display_msg:
                db.add_chat_message("assistant", display_msg)
            action_name = action_data.get("action", "").lower().strip()
            logger.info(f"Intercepted {action_name} — pending user confirmation")
            return display_msg, action_data, None, None

        final_result = await pipeline.execute_llm_response(text, llm_response, "command")

        logger.debug(f"Agent result: {final_result[:500]!r}")

        msg_type, msg = pipeline.process_output(final_result)
        logger.info(f"Completed: '{text[:50]}' → {msg_type}")

        assess_meta = None
        if (
            action_data
            and action_data.get("action", "").lower().strip() == "assess"
            and "⚠️" not in (msg or "")
        ):
            cid = db.get_session("last_assess_concept_id")
            quality = db.get_session("last_assess_quality")
            if cid and quality:
                assess_meta = {
                    "concept_id": int(cid),
                    "quality": int(quality),
                }

        # Detect quiz delivery → populate metadata for QuizQuestionView
        quiz_meta = None
        if (
            action_data
            and action_data.get("action", "").lower().strip() == "quiz"
            and action_data.get("params", {}).get("concept_id") is not None
        ):
            quiz_cid = int(action_data["params"]["concept_id"])
            quiz_concept = db.get_concept(quiz_cid)
            quiz_meta = {
                "concept_id": quiz_cid,
                "show_skip": (quiz_concept.get("review_count", 0) >= 2) if quiz_concept else False,
            }

        return msg, None, assess_meta, quiz_meta
