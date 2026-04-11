"""
Learning agent pipeline — context → LLM (with fetch loop) → execute.

Refactored: parsing, repair, and dedup extracted to separate modules.
This file is now ~300 lines of pure orchestration.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any

import config
import db
from db.preferences import get_persona, get_persona_content
from services import context as ctx
from services import state
from services import tools
from services.llm import LLMError, get_provider, get_reasoning_provider
from services.parser import (
    extract_fetch_params,
    extract_llm_action,
    parse_llm_response,
    process_output,
)
from services.repair import repair_action

logger = logging.getLogger("pipeline")

SKILLS_DIR = config.SKILLS_DIR
PREFERENCES_MD_PATH = config.PREFERENCES_MD
MAX_FETCH_ITERATIONS = 3
MAX_MAINTENANCE_ACTIONS = 5
MAX_TAXONOMY_ACTIONS = 15
DEFAULT_CONTINUATION_CONTEXT_LIMIT = 1500

# Skill sets: which skill files to load per mode category.
SKILL_SETS: dict[str, list[str]] = {
    "interactive": ["core", "quiz", "knowledge"],
    "review": ["core", "quiz"],
    "maintenance": ["core", "maintenance", "knowledge"],
    "quiz-packaging": ["core", "quiz"],
    "taxonomy": ["taxonomy"],
    # Isolated one-shot skill set for /preference edits — not reachable via
    # _call_llm/_mode_to_skill_set to avoid conversation history injection.
    "preference-edit": ["preferences"],
}

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


def _mode_to_skill_set(mode: str) -> str:
    """Map a pipeline mode string to a skill set name."""
    return {
        "command": "interactive",
        "reply": "interactive",
        "review-check": "review",
        "maintenance": "maintenance",
        "taxonomy-mode": "taxonomy",
        "quiz-packaging": "quiz-packaging",
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
    logger.info(
        f"Base prompt built for skill_set '{skill_set}' "
        f"({len(content)} chars, skills: {skill_names})"
    )
    return content


def build_system_prompt(persona: str | None = None, mode: str = "command") -> str:
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
    logger.info(
        f"System prompt built for persona '{persona}', "
        f"skill_set '{skill_set}' ({len(full_prompt)} chars)"
    )
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
    user_id = state.get_current_user()
    timeout = getattr(config, "SESSION_TIMEOUT_MINUTES", 5)
    if (
        _conv_session_name is None
        or _conv_session_last_used is None
        or (now - _conv_session_last_used).total_seconds() > timeout * 60
    ):
        _conv_session_name = f"learn_{user_id}_{now.strftime('%H%M%S')}"
        _conv_session_last_used = now
        logger.info(f"New conversation session: {_conv_session_name}")
        return _conv_session_name, True
    _conv_session_last_used = now
    return _conv_session_name, False


def _make_isolated_session_name(mode: str) -> str:
    """Return a unique session name for isolated non-interactive modes."""
    now = datetime.now()
    return f"{mode}_{now.strftime('%H%M%S_%f')}"


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
        logger.warning(
            f"[pipeline] Blocked '{action}' -- no active quiz. "
            f"concept_id={params.get('concept_id')} quality={params.get('quality')} "
            f"| anchor={db.get_session('quiz_anchor_concept_id')!r} "
            f"active_ids={db.get_session('active_concept_ids')!r}"
        )
        return f"REPLY: {message}" if message else "REPLY: (assessment skipped -- no active quiz)"

    msg_type, result = tools.execute_action(action, params)

    # Repair sub-agent: if unknown action, try to fix via kimi session
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
        anchor_before = db.get_session("quiz_anchor_concept_id")
        db.set_session("active_concept_id", None)
        db.set_session("active_concept_ids", None)
        db.set_session("quiz_anchor_concept_id", None)
        logger.debug(
            f"[quiz_anchor] CLEARED by action='{action}' "
            f"(anchor was {anchor_before!r})"
        )

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
# LLM Calls
# ============================================================================


async def _call_llm(
    mode: str,
    text: str,
    author: str,
    extra_context: str = "",
    session: str | None = None,
    is_new_session: bool = True,
) -> str:
    """Build prompt with dynamic context, call the configured LLM provider.
    Returns the raw LLM response string."""
    provider = get_provider()

    dynamic_context = ctx.build_prompt_context(text, mode, is_new_session=is_new_session)

    prompt = (
        f"{dynamic_context}\n\n"
        f'IMPORTANT — the user said: "{text}"\n'
        f"Process this request RIGHT NOW using the response format defined in the system prompt "
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


async def _call_llm_followup(
    session: str, fetch_data: str, text: str, author: str, mode: str = "command"
) -> str:
    """Lightweight follow-up call within a fetch loop session.
    See DEVNOTES.md §2.3."""
    provider = get_provider()

    prompt = (
        f"Here is the data you requested:\n\n"
        f"{fetch_data}\n\n"
        f'Now process the original request: "{text}"\n'
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


async def call_with_fetch_loop(
    mode: str,
    text: str,
    author: str,
    user_id: str = "default",
    session: str | None = None,
    is_new_session: bool | None = None,
) -> str:
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

    # Session isolation: maintenance, review-check, and taxonomy-mode use
    # dedicated sessions to prevent cross-contamination with the interactive
    # session's cached system prompt. See DEVNOTES.md §11.
    if session is not None:
        is_new = True if is_new_session is None else is_new_session
    # Session isolation: maintenance and review-check use dedicated sessions
    # to prevent cross-contamination with the interactive session's cached
    # system prompt. See DEVNOTES.md §11.
    elif mode in ("maintenance", "review-check", "taxonomy-mode"):
        session = _make_isolated_session_name(mode)
        is_new = True
        logger.info(f"Isolated session for {mode}: {session}")
    else:
        session, is_new = _get_conv_session()

    for iteration in range(MAX_FETCH_ITERATIONS + 1):
        try:
            if iteration == 0:
                llm_response = await _call_llm(
                    mode,
                    text,
                    author,
                    extra_context=extra_context,
                    session=session,
                    is_new_session=is_new,
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

            if "concept_id" in fetch_params:
                # Don't set active_concept_id while a quiz is pending —
                # the quiz anchor must remain untouched for assess.
                # Also protect multi-quiz flows.  See DEVNOTES §16.
                if not db.get_session("quiz_anchor_concept_id") and not db.get_session(
                    "active_concept_ids"
                ):
                    db.set_session("active_concept_id", str(fetch_params["concept_id"]))

            msg_type, fetch_data = tools.execute_action("fetch", fetch_params)

            if msg_type == "fetch":
                formatted = ctx.format_fetch_result(fetch_data)
            else:
                formatted = f"## Fetch Error\n{fetch_data}"

            extra_context += f"\n\n{formatted}"
            continue

        return llm_response

    return llm_response


# ============================================================================
# Two-Prompt Scheduled Quiz Pipeline
# ============================================================================

_QUIZ_GENERATOR_SKILL = SKILLS_DIR / "quiz_generator.md"


async def generate_quiz_question(concept_id: int) -> dict:
    """Prompt 1: Use the reasoning model to generate a quiz question.

    Pre-loads all concept data + related concepts, sends to the reasoning
    provider with quiz_generator.md instructions. Returns structured dict
    with question, difficulty, question_type, reasoning, concept_ids.

    Raises LLMError if the provider fails or returns unparseable output.
    """
    quiz_context = ctx.build_quiz_generator_context(concept_id)
    if not quiz_context:
        raise LLMError(f"Concept {concept_id} not found", retryable=False)

    system_prompt = ctx._read_file(_QUIZ_GENERATOR_SKILL)
    if not system_prompt:
        raise LLMError("quiz_generator.md not found", retryable=False)

    prompt = (
        f"{quiz_context}\n\n"
        f"Generate a quiz question for the primary concept above. "
        f"Respond with a single JSON object only."
    )

    provider = get_reasoning_provider()
    raw = await provider.send(
        prompt,
        system_prompt=system_prompt,
        timeout=config.COMMAND_TIMEOUT,
    )

    if not raw:
        raise LLMError("Empty response from reasoning provider", retryable=True)

    # Parse JSON from response
    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
        result = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"P1 returned unparseable JSON: {raw[:300]}")
        raise LLMError(f"Reasoning model returned invalid JSON: {e}", retryable=True)

    if not isinstance(result, dict) or "question" not in result:
        logger.error(f"P1 missing 'question' key: {result}")
        raise LLMError("Reasoning model output missing 'question' field", retryable=True)

    logger.info(
        f"P1 generated question for concept #{concept_id}: "
        f"type={result.get('question_type')}, diff={result.get('difficulty')}"
    )

    # Cache P1 output in database for debugging/inspection
    try:
        db.update_concept(concept_id, last_quiz_generator_output=json.dumps(result))
    except Exception as e:
        logger.warning(f"Failed to cache P1 output for concept {concept_id}: {e}")

    return result


async def package_quiz_for_discord(p1_result: dict, concept_id: int) -> str:
    """Prompt 2: Package a pre-generated question with persona and action format.

    Takes the structured output from generate_quiz_question() and sends it
    to the fast provider with the standard system prompt (personality, output
    format rules). Returns the LLM response string (quiz action JSON).
    """
    provider = get_provider()

    p1_json = json.dumps(p1_result, ensure_ascii=False)
    prompt = (
        f"[SCHEDULED_REVIEW] A quiz question has been pre-generated by the "
        f"analysis system. Package it for delivery to the user.\n\n"
        f"Pre-generated question data:\n{p1_json}\n\n"
        f"Instructions:\n"
        f"- Use the `quiz` action JSON format with concept_id from the data above\n"
        f"- Place the question in the `message` field, lightly rephrased for your persona voice\n"
        f"- Do NOT change the question's scope, difficulty, or core intent\n"
        f"- Do NOT fetch or generate a different question — use the one provided\n"
        f"- Respond with the quiz action JSON only"
    )

    system_prompt = build_system_prompt(mode="quiz-packaging")

    raw = await provider.send(
        prompt,
        system_prompt=system_prompt,
        timeout=config.COMMAND_TIMEOUT,
    )

    if not raw:
        raise LLMError("Empty response from packaging provider", retryable=True)

    extracted = extract_llm_action(raw)
    logger.info(f"P2 packaged quiz for concept #{concept_id} ({len(extracted)} chars)")
    return extracted


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
    detail = db.get_concept_detail(concept["id"])
    if not detail:
        return []

    topic_names = [t["title"] for t in detail.get("topics", [])]
    recent_reviews = detail.get("recent_reviews", [])
    remark_summary = detail.get("remark_summary", "")

    context_parts = [
        f"Concept: {detail['title']} (#{detail['id']})",
        f"Description: {detail.get('description', 'N/A')}",
        f"Topics: {', '.join(topic_names) if topic_names else 'untagged'}",
        f"Score: {detail['mastery_level']}/100, Reviews: {detail['review_count']}",
    ]

    if remark_summary:
        context_parts.append(f"Latest remark: {remark_summary[:100]}")

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
        stable_session = _make_isolated_session_name(mode)
        next_is_new_session = True
        logger.info(f"Stable taxonomy session: {stable_session}")

    text = f"[{mode.upper()}] {preamble}\n\n{context}\n\n"
    text += (
        f"You may execute up to {max_actions} actions this run. "
        f"Output one JSON action at a time. After each, you'll see the result "
        f"and can output another action or a final REPLY: summary."
    )

    for action_num in range(max_actions):
        llm_response = await call_with_fetch_loop(
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

        if action_name in safe_actions:
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
            context
            if continuation_context_limit <= 0
            else context[:continuation_context_limit]
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
    llm_response = await call_with_fetch_loop(
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
    system_prompt = _get_base_prompt("preference-edit")
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
    PREFERENCES_MD_PATH.write_text(content, encoding="utf-8")
    invalidate_prompt_cache()
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



async def execute_maintenance_actions(actions: list[dict]) -> list[str]:
    """Execute a list of maintenance actions that were approved by the user.
    Returns summary strings for each executed action."""
    # Ensure approved maintenance proposals keep the 'maintenance' source
    # so code-level guards (e.g. score-field stripping) still apply.
    tools.set_action_source("maintenance")

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
        logger.info(f"Approved maintenance action: {action_name} → {'error' if is_error else 'ok'}")

    return summaries
