"""Shared chat session controller for web and API clients."""

import asyncio
import json
from datetime import datetime

import config
import db
from services import backup as backup_service
from services import pipeline, state
from services.chat_actions import (
    CHAT_CONFIRMABLE_ACTIONS,
    confirmation_history_entry,
    decline_history_entry,
    is_intercepted_action,
    require_confirmable_action,
)
from services.dedup import execute_dedup_merges, format_dedup_suggestions
from services.llm import LLMError
from services.parser import guard_user_message, parse_llm_response, process_output
from services.tools import execute_action, execute_suggest_topic_accept, set_action_source
from services.tools_assess import skip_quiz

_db_initialized = False


def _response(
    message: str,
    msg_type: str = "reply",
    pending_action: dict | None = None,
    actions: list[dict] | None = None,
    clear_history: bool = False,
) -> dict:
    message = guard_user_message(message)
    payload = {
        "type": msg_type,
        "message": message,
        "pending_action": pending_action,
    }
    if actions:
        payload["actions"] = actions
    if clear_history:
        payload["clear_history"] = True
    return payload


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


def _proposal_button(
    label: str,
    action: dict,
    style: str = "secondary",
    ui_effect: str = "remove_item",
) -> dict:
    button = _button(label, action, style=style)
    button["ui_effect"] = ui_effect
    return button


def _proposal_review_block(
    title: str,
    items: list[dict],
    bulk_buttons: list[dict] | None = None,
    description: str | None = None,
) -> list[dict]:
    if not items:
        return []
    block = {"type": "proposal_review", "title": title, "items": items}
    if bulk_buttons:
        block["bulk_buttons"] = bulk_buttons
    if description:
        block["description"] = description
    return [block]


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


def _format_action_detail(action_data: dict) -> str:
    action_name = action_data.get("action", "unknown")
    params = action_data.get("params", {})

    if action_name in {"update_topic", "update_concept"}:
        target = params.get("title") or params.get("new_title") or "(untitled)"
        return f"Rename target: {target}"
    if action_name in {"unlink_topics", "unlink_concept", "delete_topic", "delete_concept"}:
        return json.dumps(params, default=str)
    return json.dumps(params, default=str) if params else ""


def _log_rejected_proposals(items: list[dict], source: str = "maintenance") -> None:
    for item in items:
        if isinstance(item, dict) and "action" in item:
            db.log_action(
                action=item.get("action", "unknown"),
                params=item.get("params", {}),
                result_type="rejected",
                result="",
                source=source,
            )
        else:
            db.log_action(
                action="dedup_merge",
                params=item,
                result_type="rejected",
                result="",
                source=source,
            )


def _dedup_proposal_actions(groups: list[dict]) -> list[dict]:
    items = []
    for idx, group in enumerate(groups):
        keep = db.get_concept(group["keep"])
        keep_title = keep["title"] if keep else f"#{group['keep']}"
        merge_titles = []
        for mid in group.get("merge", []):
            concept = db.get_concept(mid)
            merge_titles.append(concept["title"] if concept else f"#{mid}")
        detail = f"Merge: {', '.join(merge_titles)}"
        if group.get("reason"):
            detail += f"\nReason: {group['reason']}"

        items.append(
            {
                "id": f"dedup-{idx}",
                "label": f"Keep {keep_title}",
                "detail": detail,
                "buttons": [
                    _proposal_button(
                        "Approve",
                        {"kind": "apply_dedup_groups", "groups": [group]},
                        style="primary",
                    ),
                    _proposal_button(
                        "Reject",
                        {"kind": "reject_proposals", "items": [group], "source": "maintenance"},
                    ),
                ],
            }
        )

    bulk_buttons = [
        _proposal_button(
            "Approve all",
            {"kind": "apply_dedup_groups", "groups": groups},
            style="primary",
            ui_effect="remove_block",
        ),
        _proposal_button(
            "Reject all",
            {"kind": "reject_proposals", "items": groups, "source": "maintenance"},
            ui_effect="remove_block",
        ),
    ]
    return _proposal_review_block(
        "Dedup proposals",
        items,
        bulk_buttons=bulk_buttons,
        description="Approve or reject duplicate merges one group at a time.",
    )


def _action_proposal_actions(
    title: str,
    actions: list[dict],
    *,
    source: str = "maintenance",
) -> list[dict]:
    items = []
    for idx, action_data in enumerate(actions):
        items.append(
            {
                "id": f"proposal-{idx}",
                "label": action_data.get("message", action_data.get("action", "proposal")),
                "detail": _format_action_detail(action_data),
                "buttons": [
                    _proposal_button(
                        "Approve",
                        {
                            "kind": "apply_maintenance_actions",
                            "actions": [action_data],
                            "source": source,
                        },
                        style="primary",
                    ),
                    _proposal_button(
                        "Reject",
                        {"kind": "reject_proposals", "items": [action_data], "source": source},
                    ),
                ],
            }
        )

    bulk_buttons = [
        _proposal_button(
            "Approve all",
            {"kind": "apply_maintenance_actions", "actions": actions, "source": source},
            style="primary",
            ui_effect="remove_block",
        ),
        _proposal_button(
            "Reject all",
            {"kind": "reject_proposals", "items": actions, "source": source},
            ui_effect="remove_block",
        ),
    ]
    return _proposal_review_block(title, items, bulk_buttons=bulk_buttons)


def _quiz_question_actions(concept_id: int | None, choices: list[str] | None = None) -> list[dict]:
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


def _quiz_navigation_actions(concept_id: int | None, quality: int | None) -> list[dict]:
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


def _derive_actions(action_data: dict | None, reply: str) -> list[dict]:
    if not action_data or "⚠️" in (reply or ""):
        return []

    action_name = action_data.get("action", "").lower().strip()
    params = action_data.get("params", {})

    if action_name == "quiz":
        return _quiz_question_actions(params.get("concept_id"), params.get("choices"))

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
        return _quiz_navigation_actions(concept_id, quality)

    return []


def _maintenance_review_actions(
    dedup_groups: list[dict], proposed_actions: list[dict]
) -> list[dict]:
    actions = []
    if dedup_groups:
        actions.extend(_dedup_proposal_actions(dedup_groups))
    if proposed_actions:
        actions.extend(_action_proposal_actions("Maintenance proposals", proposed_actions))
    return actions


def _taxonomy_review_actions(proposed_actions: list[dict]) -> list[dict]:
    return _action_proposal_actions("Taxonomy proposals", proposed_actions)


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
    set_action_source(source)
    llm_response = await pipeline.call_with_fetch_loop("command", text, author)
    _prefix, message, action_data = parse_llm_response(llm_response)

    if action_data and is_intercepted_action(action_data) and not text.startswith("[BUTTON]"):
        display_msg = action_data.get("message", message or "")
        _record_exchange(text, display_msg)
        return _response(display_msg, msg_type="pending_confirm", pending_action=action_data)

    final_result = await pipeline.execute_llm_response(text, llm_response, "command")
    msg_type, reply = process_output(final_result)
    return _response(reply, msg_type=msg_type, actions=_derive_actions(action_data, reply))


async def _handle_review_command(raw_text: str, author: str = "chat", source: str = "chat") -> dict:
    review_lines = pipeline.handle_review_check()
    if not review_lines:
        _record_exchange(raw_text, "No concepts to review — add some topics first!")
        return _response("No concepts to review — add some topics first!")

    payload = review_lines[0]
    p1_result = None
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
        set_action_source(source)

        try:
            if cid:
                p1_result = await pipeline.generate_quiz_question(cid)
                llm_response = await pipeline.package_quiz_for_discord(p1_result, cid)
            else:
                raise LLMError("No concept_id in payload", retryable=True)
        except LLMError:
            llm_response = await pipeline.call_with_fetch_loop(
                mode="review-check",
                text=review_text,
                author=author,
            )

        final_result = await pipeline.execute_llm_response(review_text, llm_response, "reply")
        _msg_type, response = process_output(final_result)
        response = response.strip() if response else "Could not generate a review quiz. Try again?"
        db.set_session("last_quiz_question", response)
        return _response(
            response, actions=_quiz_question_actions(cid, (p1_result or {}).get("choices"))
        )
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
    if not config.MAINTENANCE_MODE_ENABLED:
        message = "Maintenance mode is currently disabled. Use /reorganize for taxonomy work."
        _record_exchange(raw_text, message)
        return _response(message)

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
        _record_exchange(raw_text, message)
        return _response(
            message,
            actions=_maintenance_review_actions(dedup_groups or [], proposed_actions),
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
        _record_exchange(raw_text, message)
        return _response(message, actions=_taxonomy_review_actions(proposed_actions))

    _record_exchange(raw_text, message)
    return _response(message)


async def handle_chat_message(text: str, author: str = "chat", source: str = "chat") -> dict:
    _ensure_db()
    text = text.strip()
    if not text:
        return _response("Message cannot be empty.", msg_type="error")

    state.last_activity_at = datetime.now()
    db.set_session("quiz_answered", None)

    if text.startswith("/"):
        command, args = _split_command(text)

        if command == "learn":
            return await _handle_learn_message(args or "hello", author=author, source=source)
        if command == "ping":
            message = "Pong!"
            _record_exchange(text, message)
            return _response(message)
        if command == "sync":
            message = "Discord slash-command sync is not relevant in this chat."
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
                message = (
                    f"Unknown persona '{target}'. Available: "
                    f"{', '.join(db.get_available_personas())}"
                )
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
            return await _handle_review_command(text, author=author, source=source)
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

    return await _handle_learn_message(text, author=author, source=source)


async def confirm_chat_action(action_data: dict, source: str = "chat") -> dict:
    _ensure_db()
    set_action_source(source)

    action = require_confirmable_action(action_data, CHAT_CONFIRMABLE_ACTIONS, "confirmed here")
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
                parts.append(
                    "Applied dedup changes:\n" + "\n".join(f"- {s}" for s in dedup_summaries)
                )
        if proposed_actions:
            maint_summaries = await pipeline.execute_maintenance_actions(proposed_actions)
            if maint_summaries:
                parts.append(
                    "Applied maintenance changes:\n" + "\n".join(f"- {s}" for s in maint_summaries)
                )
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

    raise ValueError(f"Action '{action}' is not supported by this chat confirm flow")


async def decline_chat_action(action_data: dict, source: str = "chat") -> dict:
    _ensure_db()
    set_action_source(source)
    require_confirmable_action(action_data, CHAT_CONFIRMABLE_ACTIONS, "declined here")
    db.add_chat_message("user", decline_history_entry(action_data))
    return _response("Declined.")


async def handle_chat_action(action: dict, author: str = "chat", source: str = "chat") -> dict:
    _ensure_db()
    kind = str(action.get("kind", "")).lower().strip()

    if kind == "send_message":
        message = str(action.get("message", "")).strip()
        if not message:
            raise ValueError("Action message cannot be empty")
        return await handle_chat_message(message, author=author, source=source)

    if kind == "skip_quiz":
        concept_id = action.get("concept_id")
        if concept_id is None:
            raise ValueError("skip_quiz action requires concept_id")

        result = skip_quiz(int(concept_id), user_id=author, source=source)
        if "error" in result:
            return _response(result["error"], msg_type="error")

        message = (
            f"⏭️ Skipped — score: {result['old_score']}→{result['new_score']}, "
            f"next review in {result['interval_days']}d"
        )
        return _response(message, actions=_quiz_navigation_actions(result["concept_id"], 5))

    if kind == "apply_dedup_groups":
        groups = action.get("groups", [])
        if not groups:
            raise ValueError("apply_dedup_groups requires groups")
        set_action_source("maintenance")
        summaries = await execute_dedup_merges(groups)
        summary = (
            "Applied dedup changes:\n" + "\n".join(f"- {line}" for line in summaries)
            if summaries
            else "No dedup changes were applied."
        )
        return _response(summary)

    if kind == "apply_maintenance_actions":
        actions = action.get("actions", [])
        if not actions:
            raise ValueError("apply_maintenance_actions requires actions")
        summaries = await pipeline.execute_maintenance_actions(actions)
        source_label = str(action.get("source", "maintenance")).title()
        summary = (
            f"Applied {source_label.lower()} changes:\n"
            + "\n".join(f"- {line}" for line in summaries)
            if summaries
            else f"No {source_label.lower()} changes were applied."
        )
        return _response(summary)

    if kind == "reject_proposals":
        items = action.get("items", [])
        if not items:
            raise ValueError("reject_proposals requires items")
        reject_source = str(action.get("source", "maintenance"))
        _log_rejected_proposals(items, source=reject_source)
        return _response(f"Rejected {len(items)} proposal(s).")

    if kind == "dismiss":
        return _response("")

    raise ValueError(f"Unknown chat action kind '{kind}'")


handle_webui_message = handle_chat_message
confirm_webui_action = confirm_chat_action
decline_webui_action = decline_chat_action
handle_webui_action = handle_chat_action
