"""
Learning agent pipeline — context → LLM (with fetch loop) → execute.

Refactored: parsing, repair, and dedup extracted to separate modules.
This file is now ~300 lines of pure orchestration.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

import config
import db
from services import context as ctx
from services import llm_runtime
from services import state, tools
from services.llm import LLMError, get_provider
from services.parser import (
    extract_fetch_params,
    parse_llm_response,
)
from services.repair import repair_action

logger = logging.getLogger("pipeline")


MAX_FETCH_ITERATIONS = 3
MAX_MAINTENANCE_ACTIONS = 5
MAX_TAXONOMY_ACTIONS = 15
DEFAULT_CONTINUATION_CONTEXT_LIMIT = 1500

# Actions that clear active quiz context — the LLM moved on from the quiz.
# quiz/multi_quiz are NOT here: they set new context that must persist for assess.
# multi_assess clears in tools.py but is included for consistency.
_QUIZ_CLEARING_ACTIONS = frozenset(
    {
        "assess",
        "multi_assess",
        "add_concept",
        "suggest_topic",
        "add_topic",
        "remark",
    }
)

# Actions that maintenance can execute without user confirmation.
# Everything else is collected as a proposal for the user to approve.
SAFE_MAINTENANCE_ACTIONS = frozenset(
    {
        "link_concept",  # fix untagged concepts
        "link_topics",  # fix orphan subtopics / reparent
        "delete_topic",  # remove empty topics
        "add_topic",  # create grouping parent topics
        "remark",  # add notes
        "fetch",  # data retrieval
        "list_topics",  # read-only
    }
)

# Actions that taxonomy can execute without user confirmation.
# update_topic (rename) and unlink_topics are intentionally excluded — require approval.
SAFE_TAXONOMY_ACTIONS = frozenset(
    {
        "add_topic",  # create grouping parent topics (safe — reversible)
        "link_topics",  # nest topic under new parent
        "fetch",  # data retrieval
        "list_topics",  # read-only
    }
)

_runtime_call_with_fetch_loop = llm_runtime.call_with_fetch_loop


# ============================================================================
# Initialization
# ============================================================================


def init_databases():
    """Ensure learning databases are initialised. Direct call, no subprocess."""
    db.init_databases()


# ============================================================================
# Quiz State Helpers
# ============================================================================


def is_quiz_active() -> bool:
    """Return True if any quiz session (single or multi-concept) is currently active.

    Single-quiz:  quiz_anchor_concept_id is set by _handle_quiz and cleared by
                  _QUIZ_CLEARING_ACTIONS after assess completes.
    Multi-quiz:   active_concept_ids is set by _handle_multi_quiz and cleared by
                  _handle_multi_assess at completion.

    Add new quiz types here as the system grows — callers use this one function.
    """
    return bool(db.get_session("quiz_anchor_concept_id") or db.get_session("active_concept_ids"))


# ============================================================================
# Action Execution (direct calls, no subprocess)
# ============================================================================


async def execute_action(action_data: dict) -> str:
    """Execute a parsed LLM action. Returns a prefixed output string.
    Fetch actions return FETCH: prefix; everything else returns REPLY:.
    On unknown-action errors, attempts repair via sub-agent (see DEVNOTES.md §2.2)."""
    action = action_data.get("action", "").lower().strip()
    params = action_data.get("params", {})
    message = action_data.get("message", "")

    # Defensive: if LLM put params at top level instead of in "params" dict,
    # recover them. See DEVNOTES.md §1.1 / §1.2 — this is a recurring LLM bug.
    if not params and action:
        reserved = {"action", "params", "message"}
        flat_params = {k: v for k, v in action_data.items() if k not in reserved}
        if flat_params:
            params = flat_params
            logger.warning(f"Recovered flat params for '{action}': {list(flat_params.keys())}")

    if action == "fetch":
        msg_type, result = tools.execute_action(action, params)
        if msg_type == "fetch":
            return f"FETCH: {json.dumps(result, default=str)}"
        return f"REPLY: {result}"

    # Guard: only allow assess/multi_assess when a quiz is actually active.
    # After a quiz is answered, _QUIZ_CLEARING_ACTIONS clears the session keys
    # checked by is_quiz_active(). Without this guard the LLM may re-call assess
    # on follow-up questions, triggering spurious score changes and duplicate log
    # entries. See is_quiz_active() for what constitutes an "active quiz".
    if action in ("assess", "multi_assess") and not is_quiz_active():
        recovered_pending = None
        if action == "assess":
            from services.review_state import restore_pending_review_context

            recovered_pending = restore_pending_review_context()

        if recovered_pending:
            logger.info(
                "[pipeline] Restored pending review context for assess "
                f"concept_id={recovered_pending.get('concept_id')}"
            )
        else:
            logger.warning(
                f"[pipeline] Blocked '{action}' -- no active quiz. "
                f"concept_id={params.get('concept_id')} quality={params.get('quality')} "
                f"| anchor={db.get_session('quiz_anchor_concept_id')!r} "
                f"active_ids={db.get_session('active_concept_ids')!r}"
            )
            return f"REPLY: {message}" if message else "REPLY: (assessment skipped -- no active quiz)"

    msg_type, result = tools.execute_action(action, params)

    # Repair sub-agent: if unknown action, try to fix via an isolated LLM session
    if msg_type == "error" and "Unknown action" in str(result):
        repaired = await repair_action(action_data)
        if repaired:
            r_action = repaired.get("action", "").lower().strip()
            r_params = repaired.get("params", {})
            r_message = repaired.get("message", message)
            if not r_params and r_action:
                reserved = {"action", "params", "message"}
                r_flat = {k: v for k, v in repaired.items() if k not in reserved}
                if r_flat:
                    r_params = r_flat
            msg_type, result = tools.execute_action(r_action, r_params)
            if msg_type != "error":
                message = r_message

    # Clear active quiz context when the LLM chose a non-quiz action
    # (quiz cycle complete, or intent shifted). See module-level constant.
    if action in _QUIZ_CLEARING_ACTIONS and msg_type != "error":
        from services.tools_assess import clear_quiz_state

        anchor_before = db.get_session("quiz_anchor_concept_id")
        clear_quiz_state(mark_answered=action in {"assess", "multi_assess"})
        logger.debug(f"[quiz_anchor] CLEARED by action='{action}' (anchor was {anchor_before!r})")

    if msg_type == "error":
        return f"REPLY: ⚠️ {result}"

    if message:
        return f"REPLY: {message}"
    return f"REPLY: {result}"


async def execute_llm_response(user_input: str, llm_response: str, mode: str = "command") -> str:
    """Parse and execute an LLM response, save chat history."""
    prefix, message, action_data = parse_llm_response(llm_response)

    # Phantom-add detection: LLM claims it created something in plain text
    # without a JSON action. Log-only — the AGENTS.md rule is the primary fix.
    if not action_data and prefix in ("REPLY", "ASK"):
        if re.search(r"(?i)\b(Added|Created)\s+(a\s+)?(new\s+)?(concept|topic)\b", message or ""):
            logger.warning(f"Phantom-add detected in {prefix}: {(message or '')[:120]!r}")

    if action_data:
        result = await execute_action(action_data)
        history_msg = result
        for pfx in ("REPLY: ", "FETCH: "):
            if history_msg.startswith(pfx):
                history_msg = history_msg[len(pfx) :]
                break
    elif prefix in ("REPLY", "ASK", "REMINDER", "REVIEW"):
        result = f"{prefix}: {message}"
        history_msg = message
    else:
        result = f"REPLY: {message}"
        history_msg = message

    if user_input and not user_input.startswith("[BUTTON]"):
        if user_input.startswith("[SCHEDULED_REVIEW]"):
            # Save a sanitized marker instead of the raw synthetic prompt.
            # This prevents the LLM from seeing a fake "user" message while
            # still giving it context that a review quiz is pending.
            # Payload format: "... concept: <id>|<context_string>"
            try:
                m = re.search(r":\s*(\d+)\|", user_input)
                cid = m.group(1) if m else "?"
                db.add_chat_message(
                    "user", f"[system: review quiz sent for concept #{cid} — awaiting response]"
                )
            except Exception:
                pass  # don't let marker extraction break the pipeline
        else:
            db.add_chat_message("user", user_input)
    if history_msg:
        db.add_chat_message("assistant", history_msg)

    return result


# ============================================================================
# Direct Mode Handlers (no subprocess)
# ============================================================================


def handle_maintenance() -> str | None:
    """Run DB diagnostics and return diagnostic context string.
    Returns None if no issues found."""
    maint_context = ctx.build_maintenance_context()

    if "No issues found" in maint_context:
        return None

    return maint_context


async def call_action_loop(
    mode: str,
    safe_actions: frozenset,
    max_actions: int,
    context: str,
    preamble: str,
    continuation_context_limit: int = DEFAULT_CONTINUATION_CONTEXT_LIMIT,
    action_journal: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict]]:
    """Generic LLM action loop for semi-autonomous modes (maintenance, taxonomy, etc.).

    Iterates up to *max_actions* times.  On each iteration the LLM receives
    the accumulated action log and the remaining budget.  Safe actions are
    executed immediately; everything else is deferred for user approval.

    Returns:
        (report_text, proposed_actions) — report_text is the final REPLY: summary,
        proposed_actions is a list of action dicts needing user approval.
    """
    actions_taken: list[str] = []
    proposed_actions: list[dict] = []

    source = mode.split("-")[0]  # "maintenance", "taxonomy", etc.
    tools.set_action_source(source)

    stable_session = None
    next_is_new_session = None
    if mode == "taxonomy-mode":
        stable_session = llm_runtime._make_isolated_session_name(mode)
        next_is_new_session = True
        logger.info(f"Stable taxonomy session: {stable_session}")

    text = f"[{mode.upper()}] {preamble}\n\n{context}\n\n"
    text += (
        f"You may execute up to {max_actions} actions this run. "
        f"Output one JSON action at a time. After each, you'll see the result "
        f"and can output another action or a final REPLY: summary."
    )

    for action_num in range(max_actions):
        llm_response = await _runtime_call_with_fetch_loop(
            mode=mode,
            text=text,
            author=f"{source}_agent",
            session=stable_session,
            is_new_session=next_is_new_session,
        )
        if stable_session is not None:
            next_is_new_session = False

        prefix, message, action_data = parse_llm_response(llm_response)

        if not action_data:
            final_msg = message or ""
            if actions_taken:
                action_summary = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions_taken))
                final_msg = (
                    f"**Actions taken ({len(actions_taken)}):**\n{action_summary}\n\n{final_msg}"
                )
            return f"REPLY: {final_msg}", proposed_actions

        action_name = action_data.get("action", "unknown").lower().strip()
        action_msg = action_data.get("message", "")

        if action_name in {"reply", "none"}:
            final_msg = (
                action_msg or action_data.get("params", {}).get("message", "") or message or ""
            )
            if actions_taken:
                action_summary = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions_taken))
                final_msg = (
                    f"**Actions taken ({len(actions_taken)}):**\n{action_summary}\n\n{final_msg}"
                )
            return f"REPLY: {final_msg}", proposed_actions

        if action_name in safe_actions:
            result = await execute_action(action_data)

            result_clean = result
            for pfx in ("REPLY: ", "REPLY:", "FETCH: "):
                if result_clean.startswith(pfx):
                    result_clean = result_clean[len(pfx) :]
                    break

            is_error = "\u26a0\ufe0f" in result_clean or result_clean.startswith("\u26a0")
            status = "\u274c" if is_error else "\u2705"
            actions_taken.append(f"{status} `{action_name}` — {action_msg[:80]}")
            logger.info(
                f"{source} action {action_num + 1}/{max_actions}: "
                f"{action_name} → {'error' if is_error else 'ok'}"
            )
            if action_journal is not None:
                entry: dict[str, Any] = {
                    "step": action_num + 1,
                    "action": action_name,
                    "message": action_msg,
                    "params": action_data.get("params", {}),
                    "action_data": dict(action_data),
                    "status": "error" if is_error else "executed",
                    "result": result_clean,
                    "replayable": not is_error and action_name not in {"fetch", "list_topics"},
                }
                if action_name == "add_topic" and not is_error:
                    created_topic_id = db.get_session("last_added_topic_id")
                    if created_topic_id and created_topic_id.isdigit():
                        entry["created_topic_id"] = int(created_topic_id)
                action_journal.append(entry)
        else:
            proposed_actions.append(action_data)
            actions_taken.append(
                f"\u23f3 `{action_name}` — {action_msg[:80]} *(pending user approval)*"
            )
            logger.info(
                f"{source} action {action_num + 1}/{max_actions}: "
                f"{action_name} → deferred (needs approval)"
            )
            if action_journal is not None:
                action_journal.append(
                    {
                        "step": action_num + 1,
                        "action": action_name,
                        "message": action_msg,
                        "params": action_data.get("params", {}),
                        "action_data": dict(action_data),
                        "status": "proposed",
                        "result": "pending user approval",
                        "replayable": False,
                    }
                )

        action_log = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions_taken))
        continuation_context = (
            context if continuation_context_limit <= 0 else context[:continuation_context_limit]
        )
        text = (
            f"[{mode.upper()} continuation] Actions taken so far:\n{action_log}\n\n"
            f"Original context:\n{continuation_context}\n\n"
            f"You have {max_actions - action_num - 1} action(s) remaining. "
            f"Output the next JSON action, or REPLY: with a summary if you're done."
        )

    # Exhausted action budget — ask for final summary
    text = (
        f"[{mode.upper()} final] You've used all {max_actions} actions:\n"
        + "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions_taken))
        + "\n\nOutput REPLY: with a concise summary of what you did and what still needs attention."
    )
    llm_response = await _runtime_call_with_fetch_loop(
        mode=mode,
        text=text,
        author=f"{source}_agent",
        session=stable_session,
        is_new_session=next_is_new_session,
    )
    _prefix, message, _action_data = parse_llm_response(llm_response)

    action_summary = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions_taken))
    final_msg = f"**Actions taken ({len(actions_taken)}):**\n{action_summary}\n\n{message or ''}"
    return f"REPLY: {final_msg}", proposed_actions


async def call_maintenance_loop(
    diagnostic_context: str, user_id: str = "default"
) -> tuple[str, list[dict]]:
    """Run the maintenance LLM in a loop, executing up to MAX_MAINTENANCE_ACTIONS.

    Safe actions (link_concept, delete_topic for empty topics, remark) execute
    immediately. Destructive actions (delete_concept, unlink_concept, update_concept)
    are collected as proposals for user confirmation via Discord buttons.

    Returns:
        (report_text, proposed_actions) — report_text is the REPLY: prefixed summary,
        proposed_actions is a list of action dicts needing user approval.

    Args:
        user_id: User identifier for multi-user support. Currently unused.
    """
    preamble = (
        "Triage these DB issues and fix what you can.\n\n"
        "**Note:** Destructive actions (delete_concept, unlink_concept) will be "
        "proposed to the user for approval rather than executed immediately. "
        "Do NOT attempt to merge duplicate concepts — that is handled by a "
        "separate dedup sub-agent.\n\n"
        "**IMPORTANT:** Do NOT use update_concept to change mastery_level, "
        "interval_days, next_review_at, ease_factor, or review_count. "
        "Scores are managed exclusively by the assess action during quiz sessions. "
        "For struggling concepts, add remarks or suggest splitting — never adjust scores."
    )
    return await call_action_loop(
        mode="maintenance",
        safe_actions=SAFE_MAINTENANCE_ACTIONS,
        max_actions=MAX_MAINTENANCE_ACTIONS,
        context=diagnostic_context,
        preamble=preamble,
    )


async def call_taxonomy_loop(
    taxonomy_context: str,
    max_actions: int = MAX_TAXONOMY_ACTIONS,
    continuation_context_limit: int = DEFAULT_CONTINUATION_CONTEXT_LIMIT,
    action_journal: list[dict[str, Any]] | None = None,
    operator_directive: str | None = None,
) -> tuple[str, list[dict]]:
    """Run the taxonomy reorganization LLM loop, executing up to MAX_TAXONOMY_ACTIONS.

    Safe actions (add_topic, link_topics) execute immediately.
    Destructive actions (update_topic, unlink_topics, delete_topic, unlink_concept)
    are collected as proposals for user confirmation.

    Returns:
        (report_text, proposed_actions)
    """
    preamble = (
        "Analyze this topic tree and improve its hierarchy for clarity and scannability.\n\n"
        "**Safe to execute:** add_topic (create grouping parents), link_topics (nest topics).\n"
        "**Propose for approval:** update_topic (rename), unlink_topics, delete_topic, "
        "unlink_concept.\n\n"
        "**NEVER** modify mastery_level, interval_days, next_review_at, ease_factor, or "
        "review_count. Do NOT re-propose renames listed in the ⛔ Suppressed Renames section."
    )
    if operator_directive:
        preamble = f"{preamble}\n\n## Operator Directive\n{operator_directive.strip()}"
    return await call_action_loop(
        mode="taxonomy-mode",
        safe_actions=SAFE_TAXONOMY_ACTIONS,
        max_actions=max_actions,
        context=taxonomy_context,
        preamble=preamble,
        continuation_context_limit=continuation_context_limit,
        action_journal=action_journal,
    )


def _parse_preferences_fence(raw: str) -> str:
    """Extract the content from a ```preferences fenced block in the LLM response.

    Raises ValueError if no valid block is found or the result is empty.
    """
    match = re.search(r"```preferences\s*\n(.*?)\n```", raw, re.DOTALL)
    if not match:
        raise ValueError("LLM did not produce a valid preferences block")
    content = match.group(1).strip()
    if not content:
        raise ValueError("LLM produced an empty preferences block")
    return content


async def call_preference_edit(user_text: str) -> tuple[str, str]:
    """Call the LLM to produce an edited version of preferences.md.

    Uses the 'preference-edit' skill set directly via get_provider().send() —
    deliberately bypasses _call_llm() because that function injects conversation
    history and runs extract_llm_action(), both of which corrupt the fenced output.

    Returns (preview_text, proposed_content) where preview_text is the LLM's
    one-sentence summary of the change, and proposed_content is the full updated
    file content extracted from the ```preferences fence.

    Raises ValueError if the LLM response cannot be parsed.
    """
    system_prompt = ctx._get_base_prompt("preference-edit")
    provider = get_provider()
    raw = await provider.send(
        user_text,
        system_prompt=system_prompt,
        timeout=config.COMMAND_TIMEOUT,
    )
    proposed_content = _parse_preferences_fence(raw)
    # Everything before the fence is the LLM's summary sentence
    fence_start = raw.find("```preferences")
    preview_text = raw[:fence_start].strip() if fence_start != -1 else "Preferences updated."
    return preview_text, proposed_content


async def execute_preference_update(content: str) -> str:
    """Write updated content to preferences.md and invalidate the prompt cache.

    Called by PreferenceUpdateView when the user approves a proposed edit.
    """
    ctx.PREFERENCES_MD_PATH.write_text(content, encoding="utf-8")
    ctx.invalidate_prompt_cache()
    logger.info("preferences.md updated and prompt cache invalidated")
    return "Preferences updated."


def handle_taxonomy() -> str | None:
    """Build taxonomy context. Returns the context string for use in call_taxonomy_loop().

    Unlike handle_maintenance(), this returns the context itself so the caller
    (scheduler or /reorganize command) can pass it to call_taxonomy_loop() async.
    Returns None if there are no topics yet.
    """
    if not db.get_topic_map():
        return None
    return ctx.build_taxonomy_context()


async def execute_approved_actions(actions: list[dict], *, source: str = "maintenance") -> list[str]:
    """Execute approved actions while preserving their policy source."""
    tools.set_action_source(source)

    summaries = []
    for action_data in actions:
        action_name = action_data.get("action", "unknown")
        action_msg = action_data.get("message", "")
        result = await execute_action(action_data)

        result_clean = result
        for pfx in ("REPLY: ", "REPLY:", "FETCH: "):
            if result_clean.startswith(pfx):
                result_clean = result_clean[len(pfx) :]
                break

        is_error = "\u26a0\ufe0f" in result_clean or result_clean.startswith("\u26a0")
        status = "❌" if is_error else "✅"
        summaries.append(f"{status} `{action_name}` — {action_msg[:80]}")
        logger.info(f"Approved {source} action: {action_name} → {'error' if is_error else 'ok'}")

    return summaries
