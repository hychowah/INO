"""Shared chat session controller for web and API clients."""

import asyncio
from datetime import datetime

import config
import db
from services import backup as backup_service
from services import context as ctx
from services import llm_runtime, pipeline, review_flow, state
from services import chat_admin
from services.chat_actions import (
    CHAT_CONFIRMABLE_ACTIONS,
    confirmation_history_entry,
    decline_history_entry,
    execute_lightweight_confirm,
    execute_lightweight_decline,
    require_confirmable_action,
)
from services.chat_payload import build_chat_payload
from services.chat_quiz import (
    build_quiz_followup_prompt,
    build_quiz_navigation_actions,
    build_quiz_question_actions,
    derive_quiz_actions,
    execute_skip_quiz_action,
)
from services.dedup import execute_dedup_merges
from services.learn_turn import run_learn_turn
from services.parser import parse_llm_response, process_output
from services.review_flow import generate_review_quiz_from_payload
from services.review_state import get_pending_review, register_interactive_review_delivery
from services.tools import execute_action, set_action_source

call_with_fetch_loop = llm_runtime.call_with_fetch_loop
handle_review_check = review_flow.handle_review_check

_db_initialized = False


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


def _response(output: str) -> dict:
    msg_type, message = process_output(output)
    return build_chat_payload(message, msg_type=msg_type)


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
                (
                    f"- {concept['title']} [concept:{concept['id']}] "
                    f"— score {concept['mastery_level']}/100, "
                    f"interval {concept['interval_days']}d"
                )
            )
            if remark:
                lines.append(f"  {remark[:80]}")
    else:
        lines.append("\nNothing due right now.")
    return "\n".join(lines)


async def _handle_learn_message(text: str, author: str = "chat", source: str = "chat") -> dict:
    result = await run_learn_turn(
        text,
        author,
        source=source,
        call_with_fetch_loop=call_with_fetch_loop,
        parse_response=parse_llm_response,
        execute_response=pipeline.execute_llm_response,
        process_output=process_output,
        on_pending_intercept=lambda display_msg: _record_exchange(text, display_msg),
    )

    if result.pending_action:
        return result.to_chat_payload()

    return result.to_chat_payload(
        actions=derive_quiz_actions(result.action_data, result.message),
    )


async def handle_review_request(
    *,
    author: str = "chat",
    source: str = "chat",
) -> "ReviewQuizResult | None":
    async with state.pipeline_serialized():
        return await _handle_review_request(author=author, source=source)


async def _handle_review_request(
    *,
    author: str = "chat",
    source: str = "chat",
) -> "ReviewQuizResult | None":
    _ensure_db()
    state.begin_interactive_turn()

    review_lines = handle_review_check()
    if not review_lines:
        return None

    return await generate_review_quiz_from_payload(
        review_lines[0],
        author=author,
        source=source,
        track_in_progress=True,
    )


async def _handle_review_command(raw_text: str, author: str = "chat", source: str = "chat") -> dict:
    quiz = await _handle_review_request(author=author, source=source)
    if quiz is None:
        _record_exchange(raw_text, "No concepts to review — add some topics first!")
        return build_chat_payload("No concepts to review — add some topics first!")

    if quiz.concept_id:
        register_interactive_review_delivery(quiz.concept_id, quiz.message)
    return quiz.to_chat_payload(
        quiz_actions=build_quiz_question_actions(quiz.concept_id, quiz.choices)
    )


async def _handle_preference_command(raw_text: str, args: str) -> dict:
    if not args:
        try:
            content = config.PREFERENCES_MD.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = "(preferences.md not found)"
        message = f"Your Preferences\n\n{content}"
        _record_exchange(raw_text, message)
        return build_chat_payload(message)

    preview_text, proposed_content = await pipeline.call_preference_edit(args)
    message = (
        "Proposed preference update\n\n"
        f"{preview_text}\n\n"
        "Confirm to apply this update, or decline to discard it."
    )
    _record_exchange(raw_text, message)
    return build_chat_payload(
        message,
        msg_type="pending_confirm",
        pending_action={
            "action": "preference_update",
            "message": message,
            "params": {"content": proposed_content},
        },
    )


async def _handle_maintenance_command(raw_text: str) -> dict:
    return await chat_admin.handle_maintenance_command(raw_text, record_exchange=_record_exchange)


async def _handle_reorganize_command(raw_text: str) -> dict:
    return await chat_admin.handle_reorganize_command(raw_text, record_exchange=_record_exchange)


async def handle_maintenance_request(
    *,
    raw_text: str = "/maintain",
) -> dict:
    async with state.pipeline_serialized():
        return await _handle_maintenance_request(raw_text=raw_text)


async def _handle_maintenance_request(*, raw_text: str = "/maintain") -> dict:
    _ensure_db()
    state.begin_interactive_turn()
    return await _handle_maintenance_command(raw_text)


async def handle_reorganize_request(
    *,
    raw_text: str = "/reorganize",
) -> dict:
    async with state.pipeline_serialized():
        return await _handle_reorganize_request(raw_text=raw_text)


async def _handle_reorganize_request(*, raw_text: str = "/reorganize") -> dict:
    _ensure_db()
    state.begin_interactive_turn()
    return await _handle_reorganize_command(raw_text)


async def handle_chat_message(text: str, author: str = "chat", source: str = "chat") -> dict:
    async with state.pipeline_serialized():
        return await _handle_chat_message(text, author=author, source=source)


async def _handle_chat_message(text: str, author: str = "chat", source: str = "chat") -> dict:
    _ensure_db()
    text = text.strip()
    if not text:
        return build_chat_payload("Message cannot be empty.", msg_type="error")

    state.begin_interactive_turn()

    if text.startswith("/"):
        command, args = _split_command(text)

        if command == "learn":
            return await _handle_learn_message(args or "hello", author=author, source=source)
        if command == "ping":
            message = "Pong!"
            _record_exchange(text, message)
            return build_chat_payload(message)
        if command == "sync":
            message = "Discord slash-command sync is not relevant in this chat."
            _record_exchange(text, message)
            return build_chat_payload(message)
        if command == "persona":
            if not args:
                message = _plain_persona_summary()
                _record_exchange(text, message)
                return build_chat_payload(message)

            target = args.lower()
            current = db.get_persona()
            if target == current:
                message = f"Already using {current.title()} persona."
                _record_exchange(text, message)
                return build_chat_payload(message)

            try:
                db.set_persona(target)
            except ValueError:
                message = (
                    f"Unknown persona '{target}'. Available: "
                    f"{', '.join(db.get_available_personas())}"
                )
                _record_exchange(text, message)
                return build_chat_payload(message, msg_type="error")

            ctx.invalidate_prompt_cache()
            llm_runtime.reset_conversation_session()
            message = f"Switched to {target.title()} persona. Next message will use the new style."
            _record_exchange(text, message)
            return build_chat_payload(message)
        if command == "due":
            message = _due_summary()
            _record_exchange(text, message)
            return build_chat_payload(message)
        if command == "topics":
            _msg_type, result = execute_action("list_topics", {})
            result = result.replace("**", "")
            _record_exchange(text, result)
            return build_chat_payload(result)
        if command == "clear":
            db.clear_chat_history()
            return build_chat_payload("Chat history cleared.", clear_history=True)
        if command == "review":
            return await _handle_review_command(text, author=author, source=source)
        if command == "backup":
            result = await asyncio.to_thread(backup_service.run_backup_cycle)
            message = f"{result}"
            _record_exchange(text, message)
            return build_chat_payload(message)
        if command == "maintain":
            return await _handle_maintenance_command(text)
        if command == "reorganize":
            return await _handle_reorganize_command(text)
        if command == "preference":
            return await _handle_preference_command(text, args)

        message = f"Unknown command '/{command}'."
        _record_exchange(text, message)
        return build_chat_payload(message, msg_type="error")

    return await _handle_learn_message(text, author=author, source=source)


async def confirm_chat_action(action_data: dict, source: str = "chat") -> dict:
    async with state.pipeline_serialized():
        return await _confirm_chat_action(action_data, source=source)


async def _confirm_chat_action(action_data: dict, source: str = "chat") -> dict:
    _ensure_db()

    action = require_confirmable_action(action_data, CHAT_CONFIRMABLE_ACTIONS, "confirmed here")
    message = action_data.get("message", "")
    params = action_data.get("params", {})

    if action in {"suggest_topic", "add_concept"}:
        success, note = execute_lightweight_confirm(action_data, source=source)
        return build_chat_payload(f"{message}\n\n{note}", msg_type="reply" if success else "error")

    set_action_source(source)

    if action == "preference_update":
        result = await pipeline.execute_preference_update(params.get("content", ""))
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", result)
        return build_chat_payload(f"{message}\n\n{result}")

    if action in {"maintenance_review", "taxonomy_review"}:
        summary = await chat_admin.execute_confirmed_review(action, params)
        db.add_chat_message("user", confirmation_history_entry(action_data))
        db.add_chat_message("assistant", summary)
        return build_chat_payload(f"{message}\n\n{summary}")

    raise ValueError(f"Action '{action}' is not supported by this chat confirm flow")


async def decline_chat_action(action_data: dict, source: str = "chat") -> dict:
    async with state.pipeline_serialized():
        return await _decline_chat_action(action_data, source=source)


async def _decline_chat_action(action_data: dict, source: str = "chat") -> dict:
    _ensure_db()
    action = require_confirmable_action(action_data, CHAT_CONFIRMABLE_ACTIONS, "declined here")
    if action in {"suggest_topic", "add_concept"}:
        execute_lightweight_decline(action_data)
        return build_chat_payload("Declined.")

    set_action_source(source)
    db.add_chat_message("user", decline_history_entry(action_data))
    return build_chat_payload("Declined.")


async def handle_chat_action(action: dict, author: str = "chat", source: str = "chat") -> dict:
    async with state.pipeline_serialized():
        return await _handle_chat_action(action, author=author, source=source)


async def _handle_chat_action(action: dict, author: str = "chat", source: str = "chat") -> dict:
    _ensure_db()
    kind = str(action.get("kind", "")).lower().strip()

    if kind == "send_message":
        message = str(action.get("message", "")).strip()
        if not message:
            raise ValueError("Action message cannot be empty")
        return await _handle_chat_message(message, author=author, source=source)

    if kind == "quiz_followup":
        followup = str(action.get("followup", "")).lower().strip()
        concept_id = action.get("concept_id")
        if followup == "next_due" and get_pending_review():
            return build_chat_payload(
                "⏳ A scheduled review was just sent — reply to that one first."
            )

        prompt = build_quiz_followup_prompt(followup, int(concept_id) if concept_id is not None else None)
        return await _handle_chat_message(prompt, author=author, source=source)

    if kind == "skip_quiz":
        concept_id = action.get("concept_id")
        if concept_id is None:
            raise ValueError("skip_quiz action requires concept_id")

        result = execute_skip_quiz_action(
            int(concept_id),
            user_id=state.get_current_user(),
            source=source,
        )
        if "error" in result:
            return build_chat_payload(result["error"], msg_type="error")

        return build_chat_payload(
            result["message"],
            actions=result["actions"],
        )

    admin_result = await chat_admin.handle_proposal_action(action)
    if admin_result is not None:
        return admin_result

    if kind == "dismiss":
        return build_chat_payload("")

    raise ValueError(f"Unknown chat action kind '{kind}'")

