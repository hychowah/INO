"""Local WebUI chat backend.

Provides a WebUI-native command interface that runs in-process with the bot/webui
instead of depending on a separately running FastAPI server.
"""

import asyncio
from datetime import datetime

import config
import db
from services import backup as backup_service
from services import pipeline, state
from services.chat_actions import (
    WEBUI_CONFIRMABLE_ACTIONS,
    confirmation_history_entry,
    decline_history_entry,
    is_intercepted_action,
    require_confirmable_action,
)
from services.dedup import execute_dedup_merges, format_dedup_suggestions
from services.llm import LLMError
from services.parser import parse_llm_response, process_output
from services.tools import execute_action, execute_suggest_topic_accept, set_action_source

_db_initialized = False


def _response(
    message: str,
    msg_type: str = "reply",
    pending_action: dict | None = None,
    clear_history: bool = False,
) -> dict:
    payload = {
        "type": msg_type,
        "message": message,
        "pending_action": pending_action,
    }
    if clear_history:
        payload["clear_history"] = True
    return payload


def _ensure_db() -> None:
    global _db_initialized
    if not _db_initialized:
        db.init_databases()
        _db_initialized = True


def _record_exchange(user_text: str, assistant_text: str) -> None:
    if user_text:
        db.add_chat_message("user", user_text)
    if assistant_text:
        db.add_chat_message("assistant", assistant_text)


def _split_command(text: str) -> tuple[str, str]:
    stripped = text.strip()[1:]
    command, _, args = stripped.partition(" ")
    return command.lower(), args.strip()


def _plain_persona_summary() -> str:
    current = db.get_persona()
    available = db.get_available_personas()
    descriptions = {
        "mentor": "Calm, wise senior colleague",
        "coach": "Direct, results-oriented trainer",
        "buddy": "Enthusiastic friend",
    }
    lines = [f"Active persona: {current.title()}", "", "Available presets:"]
    for persona in available:
        marker = " (active)" if persona == current else ""
        lines.append(f"- {persona.title()} — {descriptions.get(persona, '')}{marker}")
    lines.append("\nSwitch with /persona <name>")
    return "\n".join(lines)


def _due_summary() -> str:
    stats = db.get_review_stats()
    due = db.get_due_concepts(limit=10)

    lines = [
        (
            f"Due now: {stats['due_now']} | Concepts: {stats['total_concepts']} | "
            f"Avg score: {stats['avg_mastery']}/100 | Reviews this week: {stats['reviews_last_7d']}"
        )
    ]
    if due:
        lines.append("\nDue for review:")
        for concept in due:
            remark = concept.get("latest_remark", "")
            lines.append(
                f"- {concept['title']} [concept:{concept['id']}] — score {concept['mastery_level']}/100, interval {concept['interval_days']}d"
            )
            if remark:
                lines.append(f"  {remark[:80]}")
    else:
        lines.append("\nNothing due right now.")
    return "\n".join(lines)


async def _handle_learn_message(text: str, author: str = "webui") -> dict:
    set_action_source("webui")
    llm_response = await pipeline.call_with_fetch_loop("command", text, author)
    _prefix, message, action_data = parse_llm_response(llm_response)

    if action_data and is_intercepted_action(action_data):
        display_msg = action_data.get("message", message or "")
        _record_exchange(text, display_msg)
        return _response(display_msg, msg_type="pending_confirm", pending_action=action_data)

    final_result = await pipeline.execute_llm_response(text, llm_response, "command")
    msg_type, reply = process_output(final_result)
    return _response(reply, msg_type=msg_type)


async def _handle_review_command(raw_text: str) -> dict:
    review_lines = pipeline.handle_review_check()
    if not review_lines:
        _record_exchange(raw_text, "No concepts to review — add some topics first!")
        return _response("No concepts to review — add some topics first!")

    payload = review_lines[0]
    try:
        review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"

        try:
            cid = int(payload.split("|", 1)[0])
        except (ValueError, IndexError):
            cid = None

        if cid:
            db.set_session("active_concept_id", str(cid))
            db.set_session("quiz_anchor_concept_id", str(cid))

        db.set_session("review_in_progress", str(cid) if cid else "1")
        set_action_source("webui")

        try:
            if cid:
                p1_result = await pipeline.generate_quiz_question(cid)
                llm_response = await pipeline.package_quiz_for_discord(p1_result, cid)
            else:
                raise LLMError("No concept_id in payload", retryable=True)
        except LLMError:
            llm_response = await pipeline.call_with_fetch_loop(
                mode="reply",
                text=review_text,
                author="webui",
            )

        final_result = await pipeline.execute_llm_response(review_text, llm_response, "reply")
        _msg_type, response = process_output(final_result)
        response = response.strip() if response else "Could not generate a review quiz. Try again?"
        db.set_session("last_quiz_question", response)
        return _response(response)
    finally:
        db.set_session("review_in_progress", None)


async def _handle_preference_command(raw_text: str, args: str) -> dict:
    if not args:
        try:
            content = config.PREFERENCES_MD.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = "(preferences.md not found)"
        message = f"Your Preferences\n\n{content}"
        _record_exchange(raw_text, message)
        return _response(message)

    preview_text, proposed_content = await pipeline.call_preference_edit(args)
    message = (
        "Proposed preference update\n\n"
        f"{preview_text}\n\n"
        "Confirm to apply this update, or decline to discard it."
    )
    _record_exchange(raw_text, message)
    return _response(
        message,
        msg_type="pending_confirm",
        pending_action={
            "action": "preference_update",
            "message": message,
            "params": {"content": proposed_content},
        },
    )


async def _handle_maintenance_command(raw_text: str) -> dict:
    parts = []
    proposed_actions = []
    dedup_groups = None

    maint_context = pipeline.handle_maintenance()
    if maint_context:
        result, proposed_actions = await pipeline.call_maintenance_loop(maint_context)
        msg = result.removeprefix("REPLY: ").removeprefix("REPLY:").strip()
        if msg:
            parts.append(f"Maintenance\n{msg}")
    else:
        parts.append("Maintenance — no issues found.")

    existing = db.get_pending_proposal("dedup")
    if existing:
        parts.append("Dedup — pending proposal already exists in the database.")
    else:
        dedup_groups = await pipeline.handle_dedup_check()
        if dedup_groups:
            parts.append(format_dedup_suggestions(dedup_groups))
        else:
            parts.append("Dedup — no duplicates found.")

    message = "\n\n".join(parts).strip()
    if dedup_groups or proposed_actions:
        message += "\n\nConfirm to apply these changes, or decline to leave them pending."
        _record_exchange(raw_text, message)
        return _response(
            message,
            msg_type="pending_confirm",
            pending_action={
                "action": "maintenance_review",
                "message": message,
                "params": {
                    "dedup_groups": dedup_groups or [],
                    "proposed_actions": proposed_actions,
                },
            },
        )

    _record_exchange(raw_text, message)
    return _response(message)


async def _handle_reorganize_command(raw_text: str) -> dict:
    taxonomy_context = pipeline.handle_taxonomy()
    if not taxonomy_context:
        message = "Taxonomy — no topics found yet."
        _record_exchange(raw_text, message)
        return _response(message)

    final_result, proposed_actions = await pipeline.call_taxonomy_loop(taxonomy_context)
    msg = final_result.removeprefix("REPLY: ").removeprefix("REPLY:").strip()
    message = f"Taxonomy Reorganization\n\n{msg}" if msg else "Taxonomy Reorganization — complete."

    if proposed_actions:
        message += "\n\nConfirm to apply these taxonomy changes, or decline to discard them."
        _record_exchange(raw_text, message)
        return _response(
            message,
            msg_type="pending_confirm",
            pending_action={
                "action": "taxonomy_review",
                "message": message,
                "params": {"proposed_actions": proposed_actions},
            },
        )

    _record_exchange(raw_text, message)
    return _response(message)


async def handle_webui_message(text: str) -> dict:
    _ensure_db()
    text = text.strip()
    if not text:
        return _response("Message cannot be empty.", msg_type="error")

    state.last_activity_at = datetime.now()
    db.set_session("quiz_answered", None)

    if text.startswith("/"):
        command, args = _split_command(text)

        if command == "learn":
            return await _handle_learn_message(args or "hello")
        if command == "ping":
            message = "Pong!"
            _record_exchange(text, message)
            return _response(message)
        if command == "sync":
            message = "Discord slash-command sync is not relevant in WebUI chat."
            _record_exchange(text, message)
            return _response(message)
        if command == "persona":
            if not args:
                message = _plain_persona_summary()
                _record_exchange(text, message)
                return _response(message)

            target = args.lower()
            current = db.get_persona()
            if target == current:
                message = f"Already using {current.title()} persona."
                _record_exchange(text, message)
                return _response(message)

            try:
                db.set_persona(target)
            except ValueError:
                message = f"Unknown persona '{target}'. Available: {', '.join(db.get_available_personas())}"
                _record_exchange(text, message)
                return _response(message, msg_type="error")

            pipeline.invalidate_prompt_cache()
            pipeline.reset_conversation_session()
            message = f"Switched to {target.title()} persona. Next message will use the new style."
            _record_exchange(text, message)
            return _response(message)
        if command == "due":
            message = _due_summary()
            _record_exchange(text, message)
            return _response(message)
        if command == "topics":
            _msg_type, result = execute_action("list_topics", {})
            result = result.replace("**", "")
            _record_exchange(text, result)
            return _response(result)
        if command == "clear":
            db.clear_chat_history()
            return _response("Chat history cleared.", clear_history=True)
        if command == "review":
            return await _handle_review_command(text)
        if command == "backup":
            result = await asyncio.to_thread(backup_service.run_backup_cycle)
            message = f"{result}"
            _record_exchange(text, message)
            return _response(message)
        if command == "maintain":
            return await _handle_maintenance_command(text)
        if command == "reorganize":
            return await _handle_reorganize_command(text)
        if command == "preference":
            return await _handle_preference_command(text, args)

        message = f"Unknown command '/{command}'."
        _record_exchange(text, message)
        return _response(message, msg_type="error")

    return await _handle_learn_message(text)


async def confirm_webui_action(action_data: dict) -> dict:
    _ensure_db()
    set_action_source("webui")

    action = require_confirmable_action(action_data, WEBUI_CONFIRMABLE_ACTIONS, "confirmed in WebUI")
    message = action_data.get("message", "")
    params = action_data.get("params", {})

    if action == "suggest_topic":
        success, summary, _topic_id = execute_suggest_topic_accept(action_data)
        if not success:
            return _response(f"{message}\n\n⚠️ {summary}", msg_type="error")
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", summary)
        return _response(f"{message}\n\n{summary}")

    if action == "add_concept":
        msg_type, result = execute_action(action, params)
        if msg_type == "error":
            return _response(f"{message}\n\n⚠️ {result}", msg_type="error")
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", f"✅ {result}")
        return _response(f"{message}\n\n✅ {result}")

    if action == "preference_update":
        result = await pipeline.execute_preference_update(params.get("content", ""))
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", result)
        return _response(f"{message}\n\n{result}")

    if action == "maintenance_review":
        parts = []
        dedup_groups = params.get("dedup_groups", [])
        proposed_actions = params.get("proposed_actions", [])
        if dedup_groups:
            dedup_summaries = await execute_dedup_merges(dedup_groups)
            if dedup_summaries:
                parts.append("Applied dedup changes:\n" + "\n".join(f"- {s}" for s in dedup_summaries))
        if proposed_actions:
            maint_summaries = await pipeline.execute_maintenance_actions(proposed_actions)
            if maint_summaries:
                parts.append("Applied maintenance changes:\n" + "\n".join(f"- {s}" for s in maint_summaries))
        summary = "\n\n".join(parts) if parts else "No maintenance changes were applied."
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", summary)
        return _response(f"{message}\n\n{summary}")

    if action == "taxonomy_review":
        proposed_actions = params.get("proposed_actions", [])
        summaries = await pipeline.execute_maintenance_actions(proposed_actions)
        summary = (
            "Applied taxonomy changes:\n" + "\n".join(f"- {s}" for s in summaries)
            if summaries
            else "No taxonomy changes were applied."
        )
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", summary)
        return _response(f"{message}\n\n{summary}")

    raise ValueError(f"Action '{action}' is not supported by the WebUI confirm flow")


async def decline_webui_action(action_data: dict) -> dict:
    _ensure_db()
    require_confirmable_action(action_data, WEBUI_CONFIRMABLE_ACTIONS, "declined in WebUI")
    db.add_chat_message("user", decline_history_entry(action_data))
    return _response("Declined.")