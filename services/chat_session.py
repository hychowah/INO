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
    require_confirmable_action,
)
from services.dedup import execute_dedup_merges, format_dedup_suggestions
from services.learn_turn import run_learn_turn
from services.parser import guard_user_message, parse_llm_response, process_output
from services.review_flow import generate_review_quiz_from_payload
from services.review_state import register_interactive_review_delivery
from services.tools import execute_action, execute_suggest_topic_accept, set_action_source
from services.tools_assess import skip_quiz

_db_initialized = False
_PROPOSAL_ITEM_ID_KEY = "_proposal_item_id"


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


def _proposal_item_id(item: dict, index: int, *, prefix: str) -> str:
    raw = item.get(_PROPOSAL_ITEM_ID_KEY)
    return str(raw) if raw else f"{prefix}-{index}"


def _with_proposal_item_ids(items: list[dict], *, prefix: str) -> list[dict]:
    prepared = []
    for index, item in enumerate(items):
        prepared_item = dict(item)
        prepared_item.setdefault(_PROPOSAL_ITEM_ID_KEY, f"{prefix}-{index}")
        prepared.append(prepared_item)
    return prepared


def _persist_proposal(proposal_type: str, items: list[dict]) -> tuple[int, list[dict]]:
    prepared_items = _with_proposal_item_ids(items, prefix=proposal_type)
    proposal_id = db.save_proposal(proposal_type, prepared_items)
    return proposal_id, prepared_items


def _proposal_type_from_source(source: str | None) -> str | None:
    normalized = str(source or "").lower().strip()
    if normalized in {"maintenance", "taxonomy", "dedup"}:
        return normalized
    return None


def _resolve_proposal_items(action: dict, *, expected_type: str | None = None) -> tuple[dict, list[dict], list[dict]]:
    proposal_id_raw = action.get("proposal_id")
    if proposal_id_raw is None:
        raise ValueError("Action requires proposal_id")

    try:
        proposal_id = int(proposal_id_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("proposal_id must be an integer") from exc

    proposal = db.get_proposal(proposal_id)
    if proposal is None:
        raise ValueError("Proposal is no longer available")

    proposal_type = proposal["proposal_type"]
    if expected_type and proposal_type != expected_type:
        raise ValueError(f"Proposal #{proposal_id} is not a {expected_type} proposal")

    payload = proposal["payload"]
    if action.get("all"):
        return proposal, _with_proposal_item_ids(payload, prefix=proposal_type), []

    selected_ids = {str(item_id).strip() for item_id in action.get("proposal_item_ids", []) if str(item_id).strip()}
    if not selected_ids:
        raise ValueError("Action requires proposal_item_ids or all=true")

    selected = []
    remaining = []
    for index, item in enumerate(payload):
        normalized_item = dict(item)
        item_id = _proposal_item_id(normalized_item, index, prefix=proposal_type)
        normalized_item.setdefault(_PROPOSAL_ITEM_ID_KEY, item_id)
        if item_id in selected_ids:
            selected.append(normalized_item)
        else:
            remaining.append(normalized_item)

    if not selected:
        raise ValueError("Selected proposal items are no longer available")

    return proposal, selected, remaining


def _store_remaining_proposal_items(proposal: dict, remaining_items: list[dict]) -> None:
    proposal_id = int(proposal["id"])
    proposal_type = proposal["proposal_type"]
    if remaining_items:
        db.update_proposal_payload(
            proposal_id,
            _with_proposal_item_ids(remaining_items, prefix=proposal_type),
        )
        return
    db.delete_proposal(proposal_id)


def _dedup_proposal_actions(proposal_id: int, groups: list[dict]) -> list[dict]:
    items = []
    for idx, group in enumerate(groups):
        group_id = _proposal_item_id(group, idx, prefix="dedup")
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
                "id": group_id,
                "label": f"Keep {keep_title}",
                "detail": detail,
                "buttons": [
                    _proposal_button(
                        "Approve",
                        {
                            "kind": "apply_dedup_groups",
                            "proposal_id": proposal_id,
                            "proposal_item_ids": [group_id],
                        },
                        style="primary",
                    ),
                    _proposal_button(
                        "Reject",
                        {
                            "kind": "reject_proposals",
                            "proposal_id": proposal_id,
                            "proposal_item_ids": [group_id],
                            "source": "dedup",
                        },
                    ),
                ],
            }
        )

    bulk_buttons = [
        _proposal_button(
            "Approve all",
            {"kind": "apply_dedup_groups", "proposal_id": proposal_id, "all": True},
            style="primary",
            ui_effect="remove_block",
        ),
        _proposal_button(
            "Reject all",
            {"kind": "reject_proposals", "proposal_id": proposal_id, "all": True, "source": "dedup"},
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
    proposal_id: int,
    actions: list[dict],
    *,
    source: str = "maintenance",
) -> list[dict]:
    items = []
    for idx, action_data in enumerate(actions):
        item_id = _proposal_item_id(action_data, idx, prefix=source)
        items.append(
            {
                "id": item_id,
                "label": action_data.get("message", action_data.get("action", "proposal")),
                "detail": _format_action_detail(action_data),
                "buttons": [
                    _proposal_button(
                        "Approve",
                        {
                            "kind": "apply_maintenance_actions",
                            "proposal_id": proposal_id,
                            "proposal_item_ids": [item_id],
                            "source": source,
                        },
                        style="primary",
                    ),
                    _proposal_button(
                        "Reject",
                        {
                            "kind": "reject_proposals",
                            "proposal_id": proposal_id,
                            "proposal_item_ids": [item_id],
                            "source": source,
                        },
                    ),
                ],
            }
        )

    bulk_buttons = [
        _proposal_button(
            "Approve all",
            {
                "kind": "apply_maintenance_actions",
                "proposal_id": proposal_id,
                "all": True,
                "source": source,
            },
            style="primary",
            ui_effect="remove_block",
        ),
        _proposal_button(
            "Reject all",
            {
                "kind": "reject_proposals",
                "proposal_id": proposal_id,
                "all": True,
                "source": source,
            },
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
    dedup_groups: tuple[int, list[dict]] | None,
    proposed_actions: tuple[int, list[dict]] | None,
) -> list[dict]:
    actions = []
    if dedup_groups:
        dedup_proposal_id, dedup_payload = dedup_groups
        actions.extend(_dedup_proposal_actions(dedup_proposal_id, dedup_payload))
    if proposed_actions:
        maintenance_proposal_id, maintenance_payload = proposed_actions
        actions.extend(
            _action_proposal_actions(
                "Maintenance proposals",
                maintenance_proposal_id,
                maintenance_payload,
                source="maintenance",
            )
        )
    return actions


def _taxonomy_review_actions(proposed_actions: tuple[int, list[dict]]) -> list[dict]:
    proposal_id, proposal_payload = proposed_actions
    return _action_proposal_actions(
        "Taxonomy proposals",
        proposal_id,
        proposal_payload,
        source="taxonomy",
    )


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
    result = await run_learn_turn(
        text,
        author,
        source=source,
        call_with_fetch_loop=pipeline.call_with_fetch_loop,
        parse_response=parse_llm_response,
        execute_response=pipeline.execute_llm_response,
        process_output=process_output,
        on_pending_intercept=lambda display_msg: _record_exchange(text, display_msg),
    )

    if result.pending_action:
        return _response(
            result.message,
            msg_type=result.msg_type,
            pending_action=result.pending_action,
        )

    return _response(
        result.message,
        msg_type=result.msg_type,
        actions=_derive_actions(result.action_data, result.message),
    )


async def _handle_review_command(raw_text: str, author: str = "chat", source: str = "chat") -> dict:
    review_lines = pipeline.handle_review_check()
    if not review_lines:
        _record_exchange(raw_text, "No concepts to review — add some topics first!")
        return _response("No concepts to review — add some topics first!")

    quiz = await generate_review_quiz_from_payload(
        review_lines[0],
        author=author,
        source=source,
        track_in_progress=True,
    )
    if quiz.concept_id:
        register_interactive_review_delivery(quiz.concept_id, quiz.message)
    return _response(quiz.message, actions=_quiz_question_actions(quiz.concept_id, quiz.choices))


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
    maintenance_proposal = None
    dedup_proposal = None

    existing_maintenance = db.get_pending_proposal("maintenance")
    if existing_maintenance:
        parts.append("Maintenance — pending proposal already exists in the database.")
        maintenance_proposal = (
            int(existing_maintenance["id"]),
            _with_proposal_item_ids(existing_maintenance["payload"], prefix="maintenance"),
        )
    else:
        proposed_actions = []
        maint_context = pipeline.handle_maintenance()
        if maint_context:
            result, proposed_actions = await pipeline.call_maintenance_loop(maint_context)
            msg = result.removeprefix("REPLY: ").removeprefix("REPLY:").strip()
            if msg:
                parts.append(f"Maintenance\n{msg}")
        else:
            parts.append("Maintenance — no issues found.")

        if proposed_actions:
            maintenance_proposal = _persist_proposal("maintenance", proposed_actions)

    existing_dedup = db.get_pending_proposal("dedup")
    if existing_dedup:
        parts.append("Dedup — pending proposal already exists in the database.")
        dedup_proposal = (
            int(existing_dedup["id"]),
            _with_proposal_item_ids(existing_dedup["payload"], prefix="dedup"),
        )
    else:
        dedup_groups = await pipeline.handle_dedup_check()
        if dedup_groups:
            parts.append(format_dedup_suggestions(dedup_groups))
            dedup_proposal = _persist_proposal("dedup", dedup_groups)
        else:
            parts.append("Dedup — no duplicates found.")

    message = "\n\n".join(parts).strip()
    if dedup_proposal or maintenance_proposal:
        _record_exchange(raw_text, message)
        return _response(
            message,
            actions=_maintenance_review_actions(dedup_proposal, maintenance_proposal),
        )

    _record_exchange(raw_text, message)
    return _response(message)


async def _handle_reorganize_command(raw_text: str) -> dict:
    existing_taxonomy = db.get_pending_proposal("taxonomy")
    if existing_taxonomy:
        message = "Taxonomy — pending proposal already exists in the database."
        _record_exchange(raw_text, message)
        return _response(
            message,
            actions=_taxonomy_review_actions(
                (
                    int(existing_taxonomy["id"]),
                    _with_proposal_item_ids(existing_taxonomy["payload"], prefix="taxonomy"),
                )
            ),
        )

    taxonomy_context = pipeline.handle_taxonomy()
    if not taxonomy_context:
        message = "Taxonomy — no topics found yet."
        _record_exchange(raw_text, message)
        return _response(message)

    final_result, proposed_actions = await pipeline.call_taxonomy_loop(taxonomy_context)
    msg = final_result.removeprefix("REPLY: ").removeprefix("REPLY:").strip()
    message = f"Taxonomy Reorganization\n\n{msg}" if msg else "Taxonomy Reorganization — complete."

    if proposed_actions:
        taxonomy_proposal = _persist_proposal("taxonomy", proposed_actions)
        _record_exchange(raw_text, message)
        return _response(message, actions=_taxonomy_review_actions(taxonomy_proposal))

    _record_exchange(raw_text, message)
    return _response(message)


async def handle_chat_message(text: str, author: str = "chat", source: str = "chat") -> dict:
    _ensure_db()
    text = text.strip()
    if not text:
        return _response("Message cannot be empty.", msg_type="error")

    state.mark_user_activity()
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
            maint_summaries = await pipeline.execute_approved_actions(
                proposed_actions,
                source="maintenance",
            )
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
        summaries = await pipeline.execute_approved_actions(proposed_actions, source="taxonomy")
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
        proposal_id = action.get("proposal_id")
        if proposal_id is not None:
            proposal, groups, remaining_groups = _resolve_proposal_items(action, expected_type="dedup")
            summaries = await execute_dedup_merges(groups)
            _store_remaining_proposal_items(proposal, remaining_groups)
        else:
            groups = action.get("groups", [])
            if not groups:
                raise ValueError("apply_dedup_groups requires groups")
            summaries = await execute_dedup_merges(groups)
        summary = (
            "Applied dedup changes:\n" + "\n".join(f"- {line}" for line in summaries)
            if summaries
            else "No dedup changes were applied."
        )
        return _response(summary)

    if kind == "apply_maintenance_actions":
        action_source = str(action.get("source", "maintenance")).lower().strip() or "maintenance"
        proposal_id = action.get("proposal_id")
        if proposal_id is not None:
            proposal, actions, remaining_actions = _resolve_proposal_items(
                action,
                expected_type=_proposal_type_from_source(action_source),
            )
            summaries = await pipeline.execute_approved_actions(actions, source=action_source)
            _store_remaining_proposal_items(proposal, remaining_actions)
        else:
            actions = action.get("actions", [])
            if not actions:
                raise ValueError("apply_maintenance_actions requires actions")
            summaries = await pipeline.execute_approved_actions(actions, source=action_source)
        source_label = action_source.title()
        summary = (
            f"Applied {source_label.lower()} changes:\n"
            + "\n".join(f"- {line}" for line in summaries)
            if summaries
            else f"No {source_label.lower()} changes were applied."
        )
        return _response(summary)

    if kind == "reject_proposals":
        reject_source = str(action.get("source", "maintenance"))
        proposal_id = action.get("proposal_id")
        if proposal_id is not None:
            proposal, items, remaining_items = _resolve_proposal_items(
                action,
                expected_type=_proposal_type_from_source(reject_source),
            )
            _log_rejected_proposals(items, source=reject_source)
            _store_remaining_proposal_items(proposal, remaining_items)
            return _response(f"Rejected {len(items)} proposal(s).")

        items = action.get("items", [])
        if not items:
            raise ValueError("reject_proposals requires items")
        _log_rejected_proposals(items, source=reject_source)
        return _response(f"Rejected {len(items)} proposal(s).")

    if kind == "dismiss":
        return _response("")

    raise ValueError(f"Unknown chat action kind '{kind}'")


handle_webui_message = handle_chat_message
confirm_webui_action = confirm_chat_action
decline_webui_action = decline_chat_action
handle_webui_action = handle_chat_action
