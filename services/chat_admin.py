import json
from typing import Callable

import config
import db
from services import pipeline
from services.chat_payload import build_chat_payload
from services.dedup import execute_dedup_merges, format_dedup_suggestions, handle_dedup_check

_PROPOSAL_ITEM_ID_KEY = "_proposal_item_id"


def _button(label: str, action: dict, style: str = "secondary") -> dict:
    return {
        "label": label,
        "style": style,
        "action": action,
    }


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


def _format_applied_changes(label: str, summaries: list[str]) -> str:
    if summaries:
        return f"Applied {label} changes:\n" + "\n".join(f"- {line}" for line in summaries)
    return f"No {label} changes were applied."


async def execute_confirmed_review(action: str, params: dict) -> str:
    normalized_action = str(action).lower().strip()

    if normalized_action == "maintenance_review":
        parts = []
        dedup_groups = params.get("dedup_groups", [])
        proposed_actions = params.get("proposed_actions", [])

        if dedup_groups:
            dedup_summaries = await execute_dedup_merges(dedup_groups)
            if dedup_summaries:
                parts.append(_format_applied_changes("dedup", dedup_summaries))

        if proposed_actions:
            maintenance_summaries = await pipeline.execute_approved_actions(
                proposed_actions,
                source="maintenance",
            )
            if maintenance_summaries:
                parts.append(_format_applied_changes("maintenance", maintenance_summaries))

        return "\n\n".join(parts) if parts else "No maintenance changes were applied."

    if normalized_action == "taxonomy_review":
        taxonomy_summaries = await pipeline.execute_approved_actions(
            params.get("proposed_actions", []),
            source="taxonomy",
        )
        return _format_applied_changes("taxonomy", taxonomy_summaries)

    raise ValueError(f"Action '{action}' is not supported by confirmed review execution")


async def handle_maintenance_command(raw_text: str, *, record_exchange: Callable[[str, str], None]) -> dict:
    if not config.MAINTENANCE_MODE_ENABLED:
        message = "Maintenance mode is currently disabled. Use /reorganize for taxonomy work."
        record_exchange(raw_text, message)
        return build_chat_payload(message)

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
        dedup_groups = await handle_dedup_check()
        if dedup_groups:
            parts.append(format_dedup_suggestions(dedup_groups))
            dedup_proposal = _persist_proposal("dedup", dedup_groups)
        else:
            parts.append("Dedup — no duplicates found.")

    message = "\n\n".join(parts).strip()
    record_exchange(raw_text, message)
    if dedup_proposal or maintenance_proposal:
        return build_chat_payload(
            message,
            actions=_maintenance_review_actions(dedup_proposal, maintenance_proposal),
        )
    return build_chat_payload(message)


async def handle_reorganize_command(raw_text: str, *, record_exchange: Callable[[str, str], None]) -> dict:
    existing_taxonomy = db.get_pending_proposal("taxonomy")
    if existing_taxonomy:
        message = "Taxonomy — pending proposal already exists in the database."
        record_exchange(raw_text, message)
        return build_chat_payload(
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
        record_exchange(raw_text, message)
        return build_chat_payload(message)

    final_result, proposed_actions = await pipeline.call_taxonomy_loop(taxonomy_context)
    msg = final_result.removeprefix("REPLY: ").removeprefix("REPLY:").strip()
    message = f"Taxonomy Reorganization\n\n{msg}" if msg else "Taxonomy Reorganization — complete."

    record_exchange(raw_text, message)
    if proposed_actions:
        taxonomy_proposal = _persist_proposal("taxonomy", proposed_actions)
        return build_chat_payload(message, actions=_taxonomy_review_actions(taxonomy_proposal))
    return build_chat_payload(message)


async def handle_proposal_action(action: dict) -> dict | None:
    kind = str(action.get("kind", "")).lower().strip()

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
        summary = _format_applied_changes("dedup", summaries)
        return build_chat_payload(summary)

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
        summary = _format_applied_changes(action_source.lower(), summaries)
        return build_chat_payload(summary)

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
            return build_chat_payload(f"Rejected {len(items)} proposal(s).")

        items = action.get("items", [])
        if not items:
            raise ValueError("reject_proposals requires items")
        _log_rejected_proposals(items, source=reject_source)
        return build_chat_payload(f"Rejected {len(items)} proposal(s).")

    return None