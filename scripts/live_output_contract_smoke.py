#!/usr/bin/env python3
"""Live LLM output-contract smoke test.

This is intentionally NOT a pytest test. It loads the local .env through
config.py and calls the configured real provider, so it is for manual local use
when validating provider/model switches.

Usage:
  python scripts/live_output_contract_smoke.py
  python scripts/live_output_contract_smoke.py --text "Briefly explain model_validate"
  python scripts/live_output_contract_smoke.py --skip-pipeline
  python scripts/live_output_contract_smoke.py --show-raw

Exit code is non-zero only when a user-visible safety contract is violated or a
live provider call fails. A controlled formatting failure is considered safe.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows terminals.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to import path.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import db  # noqa: E402
from services import tools  # noqa: E402
from services.llm import get_provider  # noqa: E402
from services.parser import (  # noqa: E402
    CONTROLLED_FORMAT_FAILURE_MESSAGE,
    guard_user_message,
    looks_like_machine_artifact,
    parse_llm_response,
    validate_llm_output,
)
from services.pipeline import (  # noqa: E402
    _append_structured_output_hint,
    _main_response_format,
    _validate_or_retry_llm_output,
    build_system_prompt,
    call_with_fetch_loop,
)

SEP = "=" * 80
THIN = "-" * 80


def _masked(value: str | None) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "***"
    return f"***{value[-4:]}"


def _short(text: str, limit: int = 700) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [truncated]"


def _print_header(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def _print_result(name: str, ok: bool, detail: str = "") -> bool:
    icon = "✅" if ok else "❌"
    print(f"{icon} {name}")
    if detail:
        print(detail)
    return ok


def _assert_safe_visible(label: str, text: str) -> bool:
    guarded = guard_user_message(text)
    if guarded == CONTROLLED_FORMAT_FAILURE_MESSAGE and text != CONTROLLED_FORMAT_FAILURE_MESSAGE:
        return _print_result(label, False, "Visible text would be blocked by guard_user_message().")
    if looks_like_machine_artifact(text):
        return _print_result(label, False, "Visible text still looks like machine/control artifact.")
    return _print_result(label, True)


def _print_config() -> None:
    _print_header("Live provider configuration")
    print(f"Provider      : {config.LLM_PROVIDER}")
    print(f"Base URL      : {config.LLM_API_BASE_URL}")
    print(f"Model         : {config.LLM_MODEL}")
    print(f"API key       : {_masked(config.LLM_API_KEY)}")
    print(f"Output mode   : {getattr(config, 'LLM_OUTPUT_MODE', 'auto')}")
    print(f"Thinking      : {config.LLM_THINKING or '(provider default)'}")
    if config.REASONING_LLM_MODEL:
        print(f"Reasoning     : {config.REASONING_LLM_MODEL} @ {config.REASONING_LLM_BASE_URL}")
    print(f"Failure logs  : {getattr(config, 'LLM_FAILURE_LOG_DIR', config.DATA_DIR / 'llm_failures')}")
    print("\nNo secret values are printed by this script.")


async def _run_direct_structured_call(show_raw: bool) -> bool:
    _print_header("1) Direct provider structured-output call")
    provider = get_provider()
    session = "live_output_contract_direct"
    provider.clear_session(session)

    response_format = _main_response_format()
    system_prompt = "You are a live smoke-test assistant. Follow the output contract exactly."
    prompt = (
        "Answer this as a user-facing learning explanation in one sentence: "
        "What is Pydantic model_validate()?"
    )
    if response_format:
        prompt = _append_structured_output_hint(prompt, response_format)
    else:
        prompt += "\n\nRespond with exactly one REPLY: line."

    try:
        raw = await provider.send(
            prompt,
            session=session,
            system_prompt=system_prompt,
            response_format=response_format,
            timeout=45,
        )
    finally:
        provider.clear_session(session)

    if show_raw:
        print("Raw provider output:")
        print(THIN)
        print(_short(raw, 2000))
        print(THIN)

    parsed = validate_llm_output(raw, valid_actions=tools.ACTION_HANDLERS.keys())
    if not parsed.valid:
        return _print_result("Provider output validated", False, "; ".join(parsed.errors))

    prefix, message, action_data = parse_llm_response(parsed.output)
    visible = action_data.get("message", message) if action_data else message
    ok = _print_result("Provider output validated", True, f"kind={parsed.kind}, prefix={prefix}")
    ok = _assert_safe_visible("Provider visible message safe", visible) and ok
    if visible:
        print("Visible message preview:")
        print(_short(visible))
    return ok


async def _run_contract_retry(show_raw: bool) -> bool:
    _print_header("2) Real-provider contract retry from malformed DeepSeek-style output")
    provider = get_provider()
    malformed = (
        "The user is answering the quiz question. Let me assess this.\n"
        "``json\n"
        "{\n"
        '  "action": "assess",\n'
        '  "params": {"concept_id": 161, "quality": 3},\n'
        '  "message": "You got it."\n'
    )

    result = await _validate_or_retry_llm_output(
        provider=provider,
        raw=malformed,
        original_text="model_validate?",
        system_prompt=build_system_prompt(mode="command"),
        session="live_output_contract_retry",
        timeout=45,
    )

    if show_raw:
        print("Validated/retry output:")
        print(THIN)
        print(_short(result, 2000))
        print(THIN)

    prefix, message, action_data = parse_llm_response(result)
    visible = action_data.get("message", message) if action_data else message
    ok = _print_result("Retry path returned a parseable output", prefix in {"REPLY", "ASK", "REVIEW", "ACTION"}, f"prefix={prefix}")
    ok = _assert_safe_visible("Retry visible message safe", visible) and ok
    if visible == CONTROLLED_FORMAT_FAILURE_MESSAGE:
        print("ℹ️ Retry ended in controlled failure. That is safe, but the provider did not repair the malformed output.")
    elif visible:
        print("Visible message preview:")
        print(_short(visible))
    return ok


async def _run_pipeline_smoke(text: str, show_raw: bool) -> bool:
    _print_header("3) Full pipeline call_with_fetch_loop smoke")
    db.init_databases()
    provider = get_provider()

    try:
        llm_response = await call_with_fetch_loop(
            mode="command",
            text=text,
            author="live_output_contract_smoke",
            session="live_output_contract_pipeline",
            is_new_session=True,
        )
    finally:
        provider.clear_session("live_output_contract_pipeline")

    if show_raw:
        print("Pipeline returned:")
        print(THIN)
        print(_short(llm_response, 2000))
        print(THIN)

    parsed = validate_llm_output(llm_response, valid_actions=tools.ACTION_HANDLERS.keys())
    if not parsed.valid:
        return _print_result("Pipeline output validated", False, "; ".join(parsed.errors))

    prefix, message, action_data = parse_llm_response(parsed.output)
    visible = action_data.get("message", message) if action_data else message
    ok = _print_result("Pipeline output validated", True, f"kind={parsed.kind}, prefix={prefix}")
    ok = _assert_safe_visible("Pipeline visible message safe", visible) and ok
    if visible:
        print("Visible message preview:")
        print(_short(visible))
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser(description="Live .env-backed output contract smoke test")
    parser.add_argument(
        "--text",
        default=(
            "Briefly explain Pydantic model_validate() in two sentences. "
            "Do not add concepts or topics."
        ),
        help="Text for the full pipeline smoke test.",
    )
    parser.add_argument("--show-raw", action="store_true", help="Print raw model outputs.")
    parser.add_argument("--skip-direct", action="store_true", help="Skip direct provider response_format test.")
    parser.add_argument("--skip-retry", action="store_true", help="Skip malformed-output retry test.")
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip call_with_fetch_loop smoke test.")
    args = parser.parse_args()

    errors = config.validate_config()
    if errors:
        _print_header("Configuration errors")
        for error in errors:
            print(f"❌ {error}")
        return 2

    _print_config()

    checks: list[tuple[str, bool]] = []
    try:
        if not args.skip_direct:
            checks.append(("direct", await _run_direct_structured_call(args.show_raw)))
        if not args.skip_retry:
            checks.append(("retry", await _run_contract_retry(args.show_raw)))
        if not args.skip_pipeline:
            checks.append(("pipeline", await _run_pipeline_smoke(args.text, args.show_raw)))
    except Exception as exc:
        print(f"\n❌ Live smoke test raised: {type(exc).__name__}: {exc}")
        return 1

    _print_header("Summary")
    all_ok = True
    for name, ok in checks:
        all_ok = all_ok and ok
        print(f"{'✅' if ok else '❌'} {name}")

    if all_ok:
        print("\nPASS: live provider output contract is safe.")
        return 0
    print("\nFAIL: one or more live output-contract checks failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
