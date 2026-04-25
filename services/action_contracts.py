"""Action contract metadata and lightweight validation.

This module is deliberately dependency-free.  It provides the first typed
contract layer between LLM-emitted action JSON and tool execution without
requiring a large agent framework or provider-specific tool API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class ActionContract:
    """Minimal validation metadata for an LLM action."""

    required: frozenset[str] = frozenset()
    one_of: tuple[frozenset[str], ...] = ()
    optional: frozenset[str] = frozenset()
    require_message: bool = False
    description: str = ""


ACTION_CONTRACTS: dict[str, ActionContract] = {
    "none": ActionContract(require_message=True, description="No-op conversational reply."),
    "reply": ActionContract(require_message=True, description="No-op conversational reply."),
    "fetch": ActionContract(
        one_of=(frozenset({"concept_id", "topic_id", "search", "due", "stats", "cluster"}),),
        optional=frozenset({"concept_id", "topic_id", "search", "due", "stats", "cluster", "limit", "cluster_size"}),
        description="Read-only database context fetch.",
    ),
    "list_topics": ActionContract(description="Show the topic tree."),
    "add_topic": ActionContract(
        required=frozenset({"title"}),
        optional=frozenset({"description", "parent_ids"}),
        description="Create a topic.",
    ),
    "update_topic": ActionContract(
        required=frozenset({"topic_id"}),
        optional=frozenset({"title", "description"}),
        description="Update a topic.",
    ),
    "delete_topic": ActionContract(
        required=frozenset({"topic_id"}), description="Delete an empty topic."
    ),
    "link_topics": ActionContract(
        required=frozenset({"parent_id", "child_id"}), description="Link parent and child topics."
    ),
    "unlink_topics": ActionContract(
        required=frozenset({"parent_id", "child_id"}), description="Unlink parent and child topics."
    ),
    "add_concept": ActionContract(
        required=frozenset({"title"}),
        optional=frozenset({
            "description",
            "topic_ids",
            "topic_titles",
            "topic_title",
            "next_review_at",
            "remark",
        }),
        description="Create a concept.",
    ),
    "update_concept": ActionContract(
        one_of=(frozenset({"concept_id", "title"}),),
        optional=frozenset({
            "concept_id",
            "title",
            "new_title",
            "description",
            "remark",
            "mastery_level",
            "ease_factor",
            "interval_days",
            "next_review_at",
            "last_reviewed_at",
            "review_count",
        }),
        description="Update a concept.",
    ),
    "delete_concept": ActionContract(
        required=frozenset({"concept_id"}), description="Delete a concept."
    ),
    "link_concept": ActionContract(
        required=frozenset({"concept_id", "topic_ids"}), description="Link concept to topics."
    ),
    "unlink_concept": ActionContract(
        required=frozenset({"concept_id", "topic_id"}), description="Unlink concept from topic."
    ),
    "remark": ActionContract(
        required=frozenset({"content"}),
        one_of=(frozenset({"concept_id", "title"}),),
        optional=frozenset({"concept_id", "title", "content"}),
        description="Write concept memory remark.",
    ),
    "remove_relation": ActionContract(
        required=frozenset({"concept_id_a", "concept_id_b"}),
        description="Remove relation between two concepts.",
    ),
    "quiz": ActionContract(
        required=frozenset({"message"}),
        optional=frozenset({"concept_id", "topic_id", "message", "choices"}),
        require_message=True,
        description="Start a quiz question.",
    ),
    "multi_quiz": ActionContract(
        required=frozenset({"concept_ids", "message"}),
        optional=frozenset({"concept_ids", "message", "choices"}),
        require_message=True,
        description="Start a multi-concept quiz.",
    ),
    "assess": ActionContract(
        required=frozenset({"concept_id", "quality"}),
        optional=frozenset({
            "concept_id",
            "quality",
            "question_difficulty",
            "assessment",
            "question_asked",
            "user_response",
            "related_concept_ids",
            "relation_type",
            "remark",
            "message",
        }),
        require_message=True,
        description="Assess a quiz answer.",
    ),
    "multi_assess": ActionContract(
        required=frozenset({"assessments"}),
        optional=frozenset({"assessments", "llm_assessment", "assessment", "question_asked", "user_response", "message"}),
        require_message=True,
        description="Assess a multi-concept quiz answer.",
    ),
    "suggest_topic": ActionContract(
        required=frozenset({"title"}),
        optional=frozenset({"title", "description", "concepts", "parent_ids"}),
        require_message=True,
        description="Suggest creating a topic pending user confirmation.",
    ),
}

_INT_FIELDS = {
    "concept_id",
    "topic_id",
    "parent_id",
    "child_id",
    "concept_id_a",
    "concept_id_b",
    "quality",
    "question_difficulty",
    "limit",
    "cluster_size",
}
_LIST_FIELDS = {
    "topic_ids",
    "topic_titles",
    "parent_ids",
    "concept_ids",
    "related_concept_ids",
    "choices",
    "assessments",
    "concepts",
}
_STR_FIELDS = {
    "title",
    "new_title",
    "description",
    "topic_title",
    "search",
    "content",
    "message",
    "assessment",
    "llm_assessment",
    "question_asked",
    "user_response",
    "remark",
    "relation_type",
}


def _is_present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _is_intish(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        try:
            int(value)
            return True
        except ValueError:
            return False
    return False


def _field_type_error(field: str, value: Any) -> str | None:
    if field in _INT_FIELDS and _is_present(value) and not _is_intish(value):
        return f"params.{field} must be an integer"
    if field in _LIST_FIELDS and _is_present(value):
        if field in {"topic_ids", "parent_ids", "concept_ids", "related_concept_ids"} and _is_intish(value):
            return None
        if not isinstance(value, list):
            return f"params.{field} must be a list"
    if field in _STR_FIELDS and _is_present(value) and not isinstance(value, str):
        return f"params.{field} must be a string"
    return None


def validate_action_contract(
    action_data: dict[str, Any],
    *,
    valid_actions: Iterable[str] | None = None,
) -> list[str]:
    """Return validation errors for an LLM action object.

    This is intentionally lightweight: it catches malformed or dangerous control
    envelopes before side effects, while leaving deeper DB-specific validation to
    the existing tool handlers.
    """
    errors: list[str] = []
    action = str(action_data.get("action", "")).lower().strip()
    if not action:
        return ["action missing name"]

    if valid_actions is not None and action not in set(valid_actions):
        errors.append(f"unknown action: {action}")
        return errors

    params = action_data.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return ["params must be an object"]

    # Compatibility: many prompt examples put quiz/assess/suggest_topic message
    # at top level, while some tool handlers read params.message.
    merged = dict(params)
    if _is_present(action_data.get("message")) and "message" not in merged:
        merged["message"] = action_data["message"]

    contract = ACTION_CONTRACTS.get(action)
    if not contract:
        # Unknown-but-registered actions are allowed until a contract is added.
        return errors

    for field in contract.required:
        if not _is_present(merged.get(field)):
            errors.append(f"{action} requires params.{field}")

    for group in contract.one_of:
        if not any(_is_present(merged.get(field)) for field in group):
            options = " or ".join(f"params.{field}" for field in sorted(group))
            errors.append(f"{action} requires {options}")

    if contract.require_message and not _is_present(merged.get("message")):
        errors.append(f"{action} requires message")

    if action == "fetch" and merged.get("cluster") and not _is_present(merged.get("concept_id")):
        errors.append("fetch with cluster requires params.concept_id")

    for field, value in merged.items():
        err = _field_type_error(field, value)
        if err:
            errors.append(err)

    return errors


def build_action_json_schema(valid_actions: Iterable[str] | None = None) -> dict[str, Any]:
    """Build a portable JSON schema for the LLM turn envelope."""
    actions = sorted(set(valid_actions or ACTION_CONTRACTS.keys()))
    return {
        "name": "learning_agent_turn",
        "strict": False,
        "schema": {
            "type": "object",
            "additionalProperties": True,
            "required": ["action", "params", "message"],
            "properties": {
                "action": {"type": "string", "enum": actions},
                "params": {"type": "object", "additionalProperties": True},
                "message": {"type": "string"},
            },
        },
    }
