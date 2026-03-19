"""
Learning agent pipeline — context → LLM (with fetch loop) → execute.

Refactored: parsing, repair, and dedup extracted to separate modules.
This file is now ~300 lines of pure orchestration.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import config
import db
from services import context as ctx
from services import tools

from services.llm import get_provider, LLMError
from services.parser import (
    parse_llm_response,
    extract_fetch_params,
    extract_llm_action,
    process_output,
)
from services.repair import repair_action
from services.dedup import (
    handle_dedup_check,
    execute_dedup_merges,
    format_dedup_suggestions,
)
from db.preferences import get_persona, get_persona_content

logger = logging.getLogger("pipeline")

SKILLS_DIR = Path(__file__).parent.parent / "data" / "skills"
PREFERENCES_MD_PATH = Path(__file__).parent.parent / "preferences.md"
MAX_FETCH_ITERATIONS = 3
MAX_MAINTENANCE_ACTIONS = 5

# Skill sets: which skill files to load per mode category.
SKILL_SETS: dict[str, list[str]] = {
    "interactive": ["core", "quiz", "knowledge"],
    "review":      ["core", "quiz"],
    "maintenance": ["core", "maintenance", "knowledge"],
}

# Actions that maintenance can execute without user confirmation.
# Everything else is collected as a proposal for the user to approve.
SAFE_MAINTENANCE_ACTIONS = frozenset({
    'link_concept',    # fix untagged concepts
    'delete_topic',    # remove empty topics
    'remark',          # add notes
    'fetch',           # data retrieval
    'list_topics',     # read-only
})


def _mode_to_skill_set(mode: str) -> str:
    """Map a pipeline mode string to a skill set name."""
    return {
        "command":      "interactive",
        "reply":        "interactive",
        "review-check": "review",
        "maintenance":  "maintenance",
    }.get(mode, "interactive")


# Cached system prompt — keyed by (persona, skill_set), with mtimes for hot-reload.
# Format: {(persona, skill_set): (prompt_str, persona_mtime, {skill_file: mtime})}
_system_prompt_cache: dict[tuple[str, str], tuple[str, float, dict[str, float]]] = {}

# Cached base content per skill set — (content, prefs_mtime, {skill_file: mtime})
_base_prompt_cache: dict[str, tuple[str, float, dict[str, float]]] = {}


def _get_base_prompt(skill_set: str = "interactive") -> str:
    """Read skill files for *skill_set* + preferences.md, cached with mtime check."""
    global _base_prompt_cache

    skill_names = SKILL_SETS.get(skill_set, SKILL_SETS["interactive"])
    skill_paths = {name: SKILLS_DIR / f"{name}.md" for name in skill_names}

    # Gather current mtimes
    current_mtimes: dict[str, float] = {}
    for name, path in skill_paths.items():
        current_mtimes[name] = path.stat().st_mtime if path.exists() else 0
    prefs_mtime = PREFERENCES_MD_PATH.stat().st_mtime if PREFERENCES_MD_PATH.exists() else 0

    # Check cache
    if skill_set in _base_prompt_cache:
        cached_content, cached_prefs_mtime, cached_skill_mtimes = _base_prompt_cache[skill_set]
        if cached_prefs_mtime == prefs_mtime and cached_skill_mtimes == current_mtimes:
            return cached_content

    # Build fresh: concatenate skill files + preferences
    parts: list[str] = []
    for name in skill_names:
        path = skill_paths[name]
        if path.exists():
            parts.append(ctx._read_file(path))
        else:
            logger.warning(f"Skill file missing: {path}")

    prefs = ctx._read_file(PREFERENCES_MD_PATH)
    content = "\n\n".join(parts) + f"\n\n## User Preferences\n\n{prefs}"

    _base_prompt_cache[skill_set] = (content, prefs_mtime, current_mtimes)
    logger.info(f"Base prompt built for skill_set '{skill_set}' "
                f"({len(content)} chars, skills: {skill_names})")
    return content


def build_system_prompt(persona: str | None = None,
                        mode: str = "command") -> str:
    """Compose system prompt: skill files + persona + preferences.md.
    Cached per (persona, skill_set) with file mtime checks for hot-reload."""
    global _system_prompt_cache
    if persona is None:
        persona = get_persona()

    skill_set = _mode_to_skill_set(mode)

    # Check persona file mtime for hot-reload
    persona_content = get_persona_content(persona)
    persona_path = db.PERSONAS_DIR / f"{persona}.md"
    persona_mtime = persona_path.stat().st_mtime if persona_path.exists() else 0

    cache_key = (persona, skill_set)

    if cache_key in _system_prompt_cache:
        cached_prompt, cached_persona_mtime, cached_skill_mtimes = _system_prompt_cache[cache_key]
        if cached_persona_mtime == persona_mtime:
            # Verify base hasn't changed by rebuilding (uses its own cache)
            base = _get_base_prompt(skill_set)
            expected = _compose_prompt(base, persona_content)
            if cached_prompt == expected:
                return cached_prompt

    base = _get_base_prompt(skill_set)
    full_prompt = _compose_prompt(base, persona_content)

    # Gather current skill mtimes for cache
    skill_names = SKILL_SETS.get(skill_set, SKILL_SETS["interactive"])
    skill_mtimes = {}
    for name in skill_names:
        p = SKILLS_DIR / f"{name}.md"
        skill_mtimes[name] = p.stat().st_mtime if p.exists() else 0

    _system_prompt_cache[cache_key] = (full_prompt, persona_mtime, skill_mtimes)
    logger.info(f"System prompt built for persona '{persona}', "
                f"skill_set '{skill_set}' ({len(full_prompt)} chars)")
    return full_prompt


def _compose_prompt(base: str, persona_content: str) -> str:
    """Insert persona content into the base prompt (skills + prefs).
    Persona goes between skill content and User Preferences."""
    marker = "\n\n## User Preferences\n\n"
    if marker in base:
        skills_part, prefs_part = base.split(marker, 1)
        return (
            f"{skills_part}\n\n"
            f"## Active Persona\n\n{persona_content}\n\n"
            f"## User Preferences\n\n{prefs_part}"
        )
    # Fallback: append at end
    return f"{base}\n\n## Active Persona\n\n{persona_content}"


def invalidate_prompt_cache():
    """Clear all cached prompts. Call after persona switch or file edits."""
    global _system_prompt_cache, _base_prompt_cache
    _system_prompt_cache.clear()
    _base_prompt_cache.clear()
    logger.info("System prompt cache invalidated")


def reset_conversation_session():
    """Force a new conversation session. Call after persona switch so the
    OpenAI provider doesn't serve the old system prompt from cached messages."""
    global _conv_session_name, _conv_session_last_used
    if _conv_session_name:
        provider = get_provider()
        provider.clear_session(_conv_session_name)
        logger.info(f"Cleared LLM session: {_conv_session_name}")
    _conv_session_name = None
    _conv_session_last_used = None

# Conversation session state (see DEVNOTES.md §2.3)
_conv_session_name: str | None = None
_conv_session_last_used: datetime | None = None


def _get_conv_session() -> tuple[str, bool]:
    """Return a conversation session name, rotating after SESSION_TIMEOUT_MINUTES idle.
    Returns (session_name, is_new) — is_new=True means first call needs full context."""
    global _conv_session_name, _conv_session_last_used
    now = datetime.now()
    timeout = getattr(config, 'SESSION_TIMEOUT_MINUTES', 5)
    if (_conv_session_name is None or _conv_session_last_used is None
            or (now - _conv_session_last_used).total_seconds() > timeout * 60):
        _conv_session_name = f"learn_{now.strftime('%H%M%S')}"
        _conv_session_last_used = now
        logger.info(f"New conversation session: {_conv_session_name}")
        return _conv_session_name, True
    _conv_session_last_used = now
    return _conv_session_name, False


# ============================================================================
# Initialization
# ============================================================================

def init_databases():
    """Ensure learning databases are initialised. Direct call, no subprocess."""
    db.init_databases()


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
        reserved = {'action', 'params', 'message'}
        flat_params = {k: v for k, v in action_data.items() if k not in reserved}
        if flat_params:
            params = flat_params
            logger.warning(f"Recovered flat params for '{action}': {list(flat_params.keys())}")

    if action == "fetch":
        msg_type, result = tools.execute_action(action, params)
        if msg_type == 'fetch':
            return f"FETCH: {json.dumps(result, default=str)}"
        return f"REPLY: {result}"

    msg_type, result = tools.execute_action(action, params)

    # Repair sub-agent: if unknown action, try to fix via kimi session
    if msg_type == 'error' and 'Unknown action' in str(result):
        repaired = await repair_action(action_data)
        if repaired:
            r_action = repaired.get("action", "").lower().strip()
            r_params = repaired.get("params", {})
            r_message = repaired.get("message", message)
            if not r_params and r_action:
                reserved = {'action', 'params', 'message'}
                r_flat = {k: v for k, v in repaired.items() if k not in reserved}
                if r_flat:
                    r_params = r_flat
            msg_type, result = tools.execute_action(r_action, r_params)
            if msg_type != 'error':
                message = r_message

    # Clear active concept after a successful assess (quiz cycle complete)
    if action == 'assess' and msg_type != 'error':
        db.set_session('active_concept_id', None)

    if msg_type == 'error':
        return f"REPLY: ⚠️ {result}"

    if message:
        return f"REPLY: {message}"
    return f"REPLY: {result}"


async def execute_llm_response(user_input: str, llm_response: str,
                               mode: str = "command") -> str:
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
                history_msg = history_msg[len(pfx):]
                break
    elif prefix in ("REPLY", "ASK", "REMINDER", "REVIEW"):
        result = f"{prefix}: {message}"
        history_msg = message
    else:
        result = f"REPLY: {message}"
        history_msg = message

    if user_input and not user_input.startswith('[BUTTON]'):
        if user_input.startswith('[SCHEDULED_REVIEW]'):
            # Save a sanitized marker instead of the raw synthetic prompt.
            # This prevents the LLM from seeing a fake "user" message while
            # still giving it context that a review quiz is pending.
            # Payload format: "... concept: <id>|<context_string>"
            try:
                m = re.search(r':\s*(\d+)\|', user_input)
                cid = m.group(1) if m else '?'
                db.add_chat_message('user',
                    f'[system: review quiz sent for concept #{cid} — awaiting response]')
            except Exception:
                pass  # don't let marker extraction break the pipeline
        else:
            db.add_chat_message('user', user_input)
    if history_msg:
        db.add_chat_message('assistant', history_msg)

    return result


# ============================================================================
# LLM Calls
# ============================================================================

async def _call_llm(mode: str, text: str, author: str,
                    extra_context: str = "",
                    session: str | None = None) -> str:
    """Build prompt with dynamic context, call the configured LLM provider.
    Returns the raw LLM response string."""
    provider = get_provider()

    dynamic_context = ctx.build_prompt_context(text, mode)

    prompt = (
        f"{dynamic_context}\n\n"
        f"IMPORTANT — the user said: \"{text}\"\n"
        f"Process this request RIGHT NOW using the response format from AGENTS.md "
        f"(JSON action block, FETCH action, ASK:, or REPLY:). Do not describe your instructions."
    )

    if extra_context:
        prompt += f"\n\n{extra_context}"

    logger.info(
        f"{author}: '{text[:50]}...' — calling LLM "
        f"(prompt: {len(prompt)} chars{', session=' + session if session else ''})"
    )

    system_prompt = build_system_prompt(mode=mode)

    raw = await provider.send(
        prompt,
        session=session,
        system_prompt=system_prompt,
        timeout=config.COMMAND_TIMEOUT,
    )

    logger.debug(f"Raw LLM output length: {len(raw)}")

    extracted = extract_llm_action(raw)
    logger.debug(f"Extracted: {extracted[:300]!r}")

    return extracted


async def _call_llm_followup(session: str, fetch_data: str,
                             text: str, author: str,
                             mode: str = "command") -> str:
    """Lightweight follow-up call within a fetch loop session.
    See DEVNOTES.md §2.3."""
    provider = get_provider()

    prompt = (
        f"Here is the data you requested:\n\n"
        f"{fetch_data}\n\n"
        f"Now process the original request: \"{text}\"\n"
        f"Respond with a JSON action, FETCH for more data, ASK:, or REPLY:."
    )

    logger.info(
        f"{author}: '{text[:50]}...' — fetch follow-up "
        f"(prompt: {len(prompt)} chars, session={session})"
    )

    # system_prompt passed for stateless providers; session-based ones ignore it
    system_prompt = build_system_prompt(mode=mode)

    raw = await provider.send(
        prompt,
        session=session,
        system_prompt=system_prompt,
        timeout=config.COMMAND_TIMEOUT,
    )

    logger.debug(f"Raw LLM output length: {len(raw)}")

    extracted = extract_llm_action(raw)
    logger.debug(f"Extracted: {extracted[:300]!r}")

    return extracted


# ============================================================================
# Fetch Loop
# ============================================================================

async def call_with_fetch_loop(mode: str, text: str, author: str, user_id: str = "default") -> str:
    """
    Main entry point for LLM calls. Implements the fetch loop:
      1. Call LLM with lightweight context (reuse conversation session)
      2. If LLM responds with a fetch action → execute directly → follow-up in session
      3. Repeat up to MAX_FETCH_ITERATIONS times
      4. Return the final non-fetch LLM response

    Args:
        user_id: User identifier for multi-user support. Currently unused
                 (all data is global). Will be threaded to DB queries in Phase 3.
    """
    extra_context = ""

    # Session isolation: maintenance and review-check use dedicated sessions
    # to prevent cross-contamination with the interactive session's cached
    # system prompt. See DEVNOTES.md §11.
    if mode in ("maintenance", "review-check"):
        now = datetime.now()
        session = f"{mode}_{now.strftime('%H%M%S')}"
        logger.info(f"Isolated session for {mode}: {session}")
    else:
        session, is_new = _get_conv_session()

    for iteration in range(MAX_FETCH_ITERATIONS + 1):
        try:
            if iteration == 0:
                llm_response = await _call_llm(
                    mode, text, author, extra_context=extra_context,
                    session=session
                )
            else:
                llm_response = await _call_llm_followup(
                    session=session,
                    fetch_data=extra_context,
                    text=text,
                    author=author,
                    mode=mode,
                )
        except LLMError as exc:
            logger.error(f"LLM call failed: {exc} (retryable={exc.retryable})")
            if exc.retryable:
                return "REPLY: ⚠️ LLM temporarily unavailable. Please try again."
            return f"REPLY: ⚠️ LLM configuration error: {exc}"

        if not llm_response:
            return "REPLY: I didn't get a response. Could you try again?"

        fetch_params = extract_fetch_params(llm_response)

        if fetch_params and iteration < MAX_FETCH_ITERATIONS:
            logger.info(f"Fetch loop iteration {iteration + 1}: {fetch_params}")

            if 'concept_id' in fetch_params:
                db.set_session('active_concept_id',
                               str(fetch_params['concept_id']))

            msg_type, fetch_data = tools.execute_action('fetch', fetch_params)

            if msg_type == 'fetch':
                formatted = ctx.format_fetch_result(fetch_data)
            else:
                formatted = f"## Fetch Error\n{fetch_data}"

            extra_context += f"\n\n{formatted}"
            continue

        return llm_response

    return llm_response


# ============================================================================
# Direct Mode Handlers (no subprocess)
# ============================================================================

def handle_review_check() -> list[str]:
    """Find due concepts and return REVIEW payload strings.
    Falls back to the nearest upcoming concept if nothing is overdue."""
    due = db.get_due_concepts(limit=5)
    if due:
        concept = due[0]
    else:
        # Nothing overdue — fall back to the next upcoming concept
        concept = db.get_next_review_concept()
        if not concept:
            return []
    detail = db.get_concept_detail(concept['id'])
    if not detail:
        return []

    topic_names = [t['title'] for t in detail.get('topics', [])]
    recent_reviews = detail.get('recent_reviews', [])
    remarks = detail.get('remarks', [])

    context_parts = [
        f"Concept: {detail['title']} (#{detail['id']})",
        f"Description: {detail.get('description', 'N/A')}",
        f"Topics: {', '.join(topic_names) if topic_names else 'untagged'}",
        f"Score: {detail['mastery_level']}/100, "
        f"Reviews: {detail['review_count']}",
    ]

    if remarks:
        latest = remarks[0]['content'][:100]
        context_parts.append(f"Latest remark: {latest}")

    if recent_reviews:
        last = recent_reviews[0]
        context_parts.append(f"Last Q: {last.get('question_asked', 'N/A')}")
        context_parts.append(f"Last quality: {last.get('quality', 'N/A')}/5")

    context_str = " | ".join(context_parts)
    lines = [f"{concept['id']}|{context_str}"]

    if len(due) > 1:
        logger.info(f"{len(due) - 1} more concept(s) due for review")

    return lines


def handle_maintenance() -> str | None:
    """Run DB diagnostics and return diagnostic context string.
    Returns None if no issues found."""
    maint_context = ctx.build_maintenance_context()

    if "No issues found" in maint_context:
        return None

    return maint_context


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
    actions_taken = []
    proposed_actions = []

    # Set action source for audit trail
    tools.set_action_source('maintenance')

    text = (
        f"[MAINTENANCE] Triage these DB issues and fix what you can.\n\n"
        f"{diagnostic_context}\n\n"
        f"You may execute up to {MAX_MAINTENANCE_ACTIONS} actions this run. "
        f"Output one JSON action at a time. After each, you'll see the result "
        f"and can output another action or a final REPLY: summary.\n\n"
        f"**Note:** Destructive actions (delete_concept, unlink_concept) will be "
        f"proposed to the user for approval rather than executed immediately. "
        f"Do NOT attempt to merge duplicate concepts — that is handled by a "
        f"separate dedup sub-agent.\n\n"
        f"**IMPORTANT:** Do NOT use update_concept to change mastery_level, "
        f"interval_days, next_review_at, ease_factor, or review_count. "
        f"Scores are managed exclusively by the assess action during quiz sessions. "
        f"For struggling concepts, add remarks or suggest splitting — never adjust scores."
    )

    for action_num in range(MAX_MAINTENANCE_ACTIONS):
        llm_response = await call_with_fetch_loop(
            mode="maintenance",
            text=text,
            author="maintenance_agent",
            # TODO: Phase 3 — forward user_id for multi-user scoping
        )

        prefix, message, action_data = parse_llm_response(llm_response)

        if not action_data:
            # LLM is done — returned a REPLY/ASK summary
            final_msg = message or ""
            if actions_taken:
                action_summary = "\n".join(
                    f"{i+1}. {a}" for i, a in enumerate(actions_taken)
                )
                final_msg = (
                    f"**Actions taken ({len(actions_taken)}):**\n"
                    f"{action_summary}\n\n{final_msg}"
                )
            return f"REPLY: {final_msg}", proposed_actions

        action_name = action_data.get('action', 'unknown').lower().strip()
        action_msg = action_data.get('message', '')

        # Check if this action is safe to auto-execute
        if action_name in SAFE_MAINTENANCE_ACTIONS:
            # Execute immediately
            result = await execute_action(action_data)

            result_clean = result
            for pfx in ("REPLY: ", "REPLY:", "FETCH: "):
                if result_clean.startswith(pfx):
                    result_clean = result_clean[len(pfx):]
                    break

            is_error = "\u26a0\ufe0f" in result_clean or result_clean.startswith("\u26a0")
            status = "\u274c" if is_error else "\u2705"
            actions_taken.append(f"{status} `{action_name}` — {action_msg[:80]}")

            logger.info(
                f"Maintenance action {action_num + 1}/{MAX_MAINTENANCE_ACTIONS}: "
                f"{action_name} → {'error' if is_error else 'ok'}"
            )
        else:
            # Destructive action — collect as proposal, tell LLM it's deferred
            proposed_actions.append(action_data)
            actions_taken.append(
                f"⏳ `{action_name}` — {action_msg[:80]} *(pending user approval)*"
            )

            logger.info(
                f"Maintenance action {action_num + 1}/{MAX_MAINTENANCE_ACTIONS}: "
                f"{action_name} → deferred (needs approval)"
            )

        # Build continuation prompt with results so far
        action_log = "\n".join(
            f"{i+1}. {a}" for i, a in enumerate(actions_taken)
        )
        text = (
            f"[MAINTENANCE continuation] Actions taken so far:\n{action_log}\n\n"
            f"Original diagnostic report:\n{diagnostic_context[:1500]}\n\n"
            f"You have {MAX_MAINTENANCE_ACTIONS - action_num - 1} action(s) remaining. "
            f"Output the next JSON action, or REPLY: with a summary if you're done."
        )

    # Exhausted all action slots — ask LLM for final summary
    text = (
        f"[MAINTENANCE final] You've used all {MAX_MAINTENANCE_ACTIONS} actions:\n"
        + "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions_taken))
        + "\n\nOutput REPLY: with a concise summary of what you did and what still needs attention."
    )
    # TODO: Phase 3 — forward user_id for multi-user scoping
    llm_response = await call_with_fetch_loop(
        mode="maintenance", text=text, author="maintenance_agent"
    )
    _prefix, message, _action_data = parse_llm_response(llm_response)

    action_summary = "\n".join(
        f"{i+1}. {a}" for i, a in enumerate(actions_taken)
    )
    final_msg = (
        f"**Actions taken ({len(actions_taken)}):**\n"
        f"{action_summary}\n\n{message or ''}"
    )
    return f"REPLY: {final_msg}", proposed_actions


async def execute_maintenance_actions(actions: list[dict]) -> list[str]:
    """Execute a list of maintenance actions that were approved by the user.
    Returns summary strings for each executed action."""
    # Ensure approved maintenance proposals keep the 'maintenance' source
    # so code-level guards (e.g. score-field stripping) still apply.
    tools.set_action_source('maintenance')

    summaries = []
    for action_data in actions:
        action_name = action_data.get('action', 'unknown')
        action_msg = action_data.get('message', '')
        result = await execute_action(action_data)

        result_clean = result
        for pfx in ("REPLY: ", "REPLY:", "FETCH: "):
            if result_clean.startswith(pfx):
                result_clean = result_clean[len(pfx):]
                break

        is_error = "\u26a0\ufe0f" in result_clean or result_clean.startswith("\u26a0")
        status = "❌" if is_error else "✅"
        summaries.append(f"{status} `{action_name}` — {action_msg[:80]}")
        logger.info(f"Approved maintenance action: {action_name} → "
                     f"{'error' if is_error else 'ok'}")

    return summaries