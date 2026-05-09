import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import config
import db
from services import context as ctx
from services import state, tools
from services.action_contracts import build_action_json_schema
from services.llm import LLMError, get_provider
from services.parser import CONTROLLED_FORMAT_FAILURE_MESSAGE, extract_fetch_params, validate_llm_output

logger = logging.getLogger("pipeline")

MAX_FETCH_ITERATIONS = 3


# Conversation session state (see DEVNOTES.md §2.3)
_conv_sessions: dict[str, tuple[str, datetime]] = {}


def reset_conversation_session(provider_factory=None):
    """Force a new conversation session for the current user."""
    user_id = state.get_current_user()
    session_state = _conv_sessions.pop(user_id, None)
    if session_state:
        session_name, _last_used = session_state
        provider = (provider_factory or get_provider)()
        provider.clear_session(session_name)
        logger.info("Cleared LLM session: %s user=%s", session_name, user_id)


def _get_conv_session() -> tuple[str, bool]:
    """Return a conversation session name, rotating after idle timeout."""
    now = datetime.now()
    user_id = state.get_current_user()
    timeout = getattr(config, "SESSION_TIMEOUT_MINUTES", 5)
    existing = _conv_sessions.get(user_id)
    session_name = existing[0] if existing else None
    last_used = existing[1] if existing else None
    if (
        session_name is None
        or last_used is None
        or (now - last_used).total_seconds() > timeout * 60
    ):
        session_name = f"learn_{user_id}_{now.strftime('%H%M%S')}"
        _conv_sessions[user_id] = (session_name, now)
        logger.info("New conversation session: %s user=%s", session_name, user_id)
        return session_name, True
    _conv_sessions[user_id] = (session_name, now)
    return session_name, False


def _make_isolated_session_name(mode: str) -> str:
    """Return a unique session name for isolated non-interactive modes."""
    now = datetime.now()
    return f"{mode}_{now.strftime('%H%M%S_%f')}"


def _format_contract_retry_prompt(original_text: str, malformed_output: str) -> str:
    """Build the single hidden retry prompt for malformed provider output."""
    valid_actions = ", ".join(sorted(tools.ACTION_HANDLERS.keys()))
    return (
        "Your previous response violated the required output contract.\n"
        "Convert it into exactly ONE valid response. Return ONLY one of these forms:\n"
        "1. A JSON object with keys: action, params, message.\n"
        "2. ASK: <clarifying question>\n"
        "3. REPLY: <user-facing answer>\n"
        "4. REVIEW: <quiz question>\n\n"
        f"Valid action names: {valid_actions}\n\n"
        f"Original user message:\n{original_text}\n\n"
        "Malformed previous response:\n"
        f"{malformed_output[:4000]}"
    )


def _controlled_contract_failure() -> str:
    return f"REPLY: {CONTROLLED_FORMAT_FAILURE_MESSAGE}"


def _main_response_format() -> dict[str, Any] | None:
    """Return provider response_format for the main conversation path."""
    mode = getattr(config, "LLM_OUTPUT_MODE", "auto")
    if mode == "legacy":
        return None
    if mode == "json_schema":
        return {"type": "json_schema", "json_schema": build_action_json_schema(tools.ACTION_HANDLERS)}
    if mode in {"auto", "json_object"}:
        return {"type": "json_object"}
    logger.warning("Unknown LLM_OUTPUT_MODE=%r; using legacy output mode", mode)
    return None


def _append_structured_output_hint(prompt: str, response_format: dict[str, Any] | None) -> str:
    """Add runtime instructions required when provider JSON mode is active."""
    if not response_format:
        return prompt
    return (
        f"{prompt}\n\n"
        "## Provider JSON Output Mode\n"
        "Return exactly one JSON object and no markdown fences. For database/tool actions, "
        "use the normal action JSON shape. For a normal answer, clarification question, "
        "or final summary, use this pass-through shape instead:\n"
        '{"action":"reply","params":{},"message":"Your user-facing text here"}\n'
        "Do not emit REPLY:, ASK:, REVIEW:, explanations about your instructions, or "
        "multiple JSON objects."
    )


def _write_llm_failure_log(
    *,
    stage: str,
    raw: str,
    errors: list[str],
    original_text: str,
    session: str | None,
) -> str:
    """Write malformed completion details to a private ignored log file."""
    failure_id = uuid.uuid4().hex[:12]
    payload: dict[str, Any] = {
        "id": failure_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "session": session,
        "errors": errors,
        "original_text_snippet": original_text[:1000],
        "raw_length": len(raw),
    }
    if getattr(config, "LLM_LOG_FAILURE_RAW", True):
        payload["raw"] = raw
    else:
        payload["raw_snippet"] = raw[:1000]

    try:
        log_dir = getattr(config, "LLM_FAILURE_LOG_DIR", config.DATA_DIR / "llm_failures")
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{failure_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("Failed to write private LLM failure log", exc_info=True)
    return failure_id


async def _validate_or_retry_llm_output(
    *,
    provider,
    raw: str,
    original_text: str,
    system_prompt: str,
    session: str | None,
    timeout: int,
) -> str:
    """Validate a provider completion, retrying once on contract failure."""
    valid_actions = tools.ACTION_HANDLERS.keys()
    parsed = validate_llm_output(raw, valid_actions=valid_actions)
    if parsed.valid:
        extracted = parsed.output
        logger.debug(f"Extracted: {extracted[:300]!r}")
        return extracted

    failure_id = _write_llm_failure_log(
        stage="initial",
        raw=raw,
        errors=parsed.errors,
        original_text=original_text,
        session=session,
    )
    logger.warning(
        "Invalid LLM output contract id=%s: %s",
        failure_id,
        "; ".join(parsed.errors),
    )
    if session:
        try:
            provider.clear_session(session)
            logger.info(f"Cleared contaminated LLM session after invalid output: {session}")
        except Exception:
            logger.warning("Failed to clear LLM session after invalid output", exc_info=True)

    retry_prompt = _format_contract_retry_prompt(original_text, raw)
    try:
        retry_raw = await provider.send(
            retry_prompt,
            session=None,
            system_prompt=system_prompt,
            timeout=min(timeout, 30),
        )
    except LLMError:
        raise
    except Exception as exc:
        raise LLMError(f"LLM contract retry failed: {exc}", retryable=True) from exc

    retry_parsed = validate_llm_output(retry_raw, valid_actions=valid_actions)
    if retry_parsed.valid:
        extracted = retry_parsed.output
        logger.info("LLM output contract retry succeeded")
        logger.debug(f"Extracted after retry: {extracted[:300]!r}")
        return extracted

    retry_failure_id = _write_llm_failure_log(
        stage="retry",
        raw=retry_raw,
        errors=retry_parsed.errors,
        original_text=original_text,
        session=None,
    )
    logger.error(
        "LLM output contract retry failed id=%s: %s",
        retry_failure_id,
        "; ".join(retry_parsed.errors),
    )
    return _controlled_contract_failure()


async def _call_llm(
    mode: str,
    text: str,
    author: str,
    extra_context: str = "",
    session: str | None = None,
    is_new_session: bool = True,
) -> str:
    """Build prompt with dynamic context, call the configured LLM provider."""
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

    system_prompt = ctx.build_system_prompt(mode=mode)

    response_format = _main_response_format()
    prompt = _append_structured_output_hint(prompt, response_format)

    raw = await provider.send(
        prompt,
        session=session,
        system_prompt=system_prompt,
        response_format=response_format,
        timeout=config.COMMAND_TIMEOUT,
    )

    logger.debug(f"Raw LLM output length: {len(raw)}")
    return await _validate_or_retry_llm_output(
        provider=provider,
        raw=raw,
        original_text=text,
        system_prompt=system_prompt,
        session=session,
        timeout=config.COMMAND_TIMEOUT,
    )


async def _call_llm_followup(
    session: str, fetch_data: str, text: str, author: str, mode: str = "command"
) -> str:
    """Lightweight follow-up call within a fetch loop session."""
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

    system_prompt = ctx.build_system_prompt(mode=mode)

    response_format = _main_response_format()
    prompt = _append_structured_output_hint(prompt, response_format)

    raw = await provider.send(
        prompt,
        session=session,
        system_prompt=system_prompt,
        response_format=response_format,
        timeout=config.COMMAND_TIMEOUT,
    )

    logger.debug(f"Raw LLM output length: {len(raw)}")
    return await _validate_or_retry_llm_output(
        provider=provider,
        raw=raw,
        original_text=text,
        system_prompt=system_prompt,
        session=session,
        timeout=config.COMMAND_TIMEOUT,
    )


async def call_with_fetch_loop(
    mode: str,
    text: str,
    author: str,
    user_id: str = "default",
    session: str | None = None,
    is_new_session: bool | None = None,
    *,
    call_llm: Callable[..., Awaitable[str]] | None = None,
    call_llm_followup: Callable[..., Awaitable[str]] | None = None,
    get_conv_session: Callable[[], tuple[str, bool]] | None = None,
    make_isolated_session_name: Callable[[str], str] | None = None,
) -> str:
    """Main entry point for LLM calls with dependency-injected seams."""
    del user_id
    extra_context = ""
    call_llm = call_llm or _call_llm
    call_llm_followup = call_llm_followup or _call_llm_followup
    get_conv_session = get_conv_session or _get_conv_session
    make_isolated_session_name = make_isolated_session_name or _make_isolated_session_name

    if session is not None:
        is_new = True if is_new_session is None else is_new_session
    elif mode in ("maintenance", "review-check", "taxonomy-mode"):
        session = make_isolated_session_name(mode)
        is_new = True
        logger.info(f"Isolated session for {mode}: {session}")
    else:
        session, is_new = get_conv_session()

    for iteration in range(MAX_FETCH_ITERATIONS + 1):
        try:
            if iteration == 0:
                llm_response = await call_llm(
                    mode,
                    text,
                    author,
                    extra_context=extra_context,
                    session=session,
                    is_new_session=is_new,
                )
            else:
                llm_response = await call_llm_followup(
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