#!/usr/bin/env python3
"""
Learning Agent — CLI entry point (standalone testing/debugging).

The Discord bot does NOT call this as a subprocess anymore.
Pipeline.py calls db/tools/context directly. This file is kept
for manual testing and the webui.

Modes: command, reply, review-check, maintenance, fetch, context-only
"""

import argparse
import sys
import json
import re
from pathlib import Path

# Ensure UTF-8 output (Windows fix)
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import db
from services import tools
from services import context as ctx
from services.parser import parse_llm_response

# Set action source for audit trail
tools.set_action_source('cli')


# ============================================================================
# Action Execution
# ============================================================================

def execute_action(action_data: dict) -> str:
    """Execute a parsed LLM action. Returns a prefixed output string."""
    action = action_data.get("action", "")
    params = action_data.get("params", {})
    message = action_data.get("message", "")

    # The fetch action returns data for the fetch loop — not a user message
    if action == "fetch":
        msg_type, result = tools.execute_action(action, params)
        if msg_type == 'fetch':
            return f"FETCH: {json.dumps(result, default=str)}"
        return f"REPLY: {result}"

    # Guard: mirror pipeline.execute_action — block assess/multi_assess when no
    # quiz is active. Prevents duplicate score writes during CLI/webui testing.
    if action in ('assess', 'multi_assess'):
        if not db.get_session('quiz_anchor_concept_id') and not db.get_session('active_concept_ids'):
            return f"REPLY: {message}" if message else "REPLY: (assessment skipped -- no active quiz)"

    # All other actions
    msg_type, result = tools.execute_action(action, params)

    if msg_type == 'error':
        return f"REPLY: ⚠️ {result}"

    # Prefer the LLM's message if it provided one
    if message:
        return f"REPLY: {message}"
    return f"REPLY: {result}"


# ============================================================================
# Modes
# ============================================================================

def mode_context_only(user_input: str, mode: str):
    """Output lightweight context (for debugging / standalone use)."""
    context = ctx.build_prompt_context(user_input, mode)
    print(context)


def mode_fetch(fetch_params: str):
    """Execute a fetch query and output the result as JSON.
    fetch_params is a JSON string like {"topic_id": 3}."""
    try:
        params = json.loads(fetch_params)
    except json.JSONDecodeError:
        print(json.dumps({"error": f"Invalid fetch params: {fetch_params}"}))
        return

    msg_type, result = tools.execute_action('fetch', params)
    print(json.dumps(result, default=str))


def mode_command(user_input: str):
    """Process a command from the user.
    If stdin has data, it's the LLM response — parse and execute it.
    Otherwise output PROMPT: to signal that LLM call is needed."""
    db.init_databases()

    # Check for stdin (LLM response piped in)
    llm_response = None
    if not sys.stdin.isatty():
        llm_response = sys.stdin.read().strip()

    if llm_response:
        # Parse and execute the LLM's response
        prefix, message, action_data = parse_llm_response(llm_response)

        if action_data:
            result = execute_action(action_data)
            print(result)
            # Save the executed result (has concept IDs etc.) to chat history
            history_msg = result
            for pfx in ("REPLY: ", "FETCH: "):
                if history_msg.startswith(pfx):
                    history_msg = history_msg[len(pfx):]
                    break
        elif prefix in ("REPLY", "ASK", "REMINDER", "REVIEW"):
            print(f"{prefix}: {message}")
            history_msg = message
        else:
            print(f"REPLY: {message}")
            history_msg = message

        # Save to chat history
        if user_input:
            db.add_chat_message('user', user_input)
        if history_msg:
            db.add_chat_message('assistant', history_msg)
    else:
        # No LLM response — check if we can handle this locally
        lower = user_input.lower().strip() if user_input else ""

        if not lower or lower in ('list', 'topics', 'show topics', 'show my topics'):
            # Handle list locally
            msg_type, result = tools.execute_action('list_topics', {})
            print(f"REPLY: {result}")
        else:
            # Need LLM — output prompt signal
            print("PROMPT: LLM_NEEDED")


def mode_reply(user_input: str):
    """Process a follow-up message in an active session."""
    db.init_databases()

    llm_response = None
    if not sys.stdin.isatty():
        llm_response = sys.stdin.read().strip()

    if llm_response:
        prefix, message, action_data = parse_llm_response(llm_response)

        if action_data:
            result = execute_action(action_data)
            print(result)
            history_msg = result
            for pfx in ("REPLY: ", "FETCH: "):
                if history_msg.startswith(pfx):
                    history_msg = history_msg[len(pfx):]
                    break
        elif prefix in ("REPLY", "ASK", "REMINDER", "REVIEW"):
            print(f"{prefix}: {message}")
            history_msg = message
        else:
            print(f"REPLY: {message}")
            history_msg = message

        if user_input:
            db.add_chat_message('user', user_input)
        if history_msg:
            db.add_chat_message('assistant', history_msg)
    else:
        # In reply mode without LLM response, always need LLM
        print("PROMPT: LLM_NEEDED")


def mode_review_check():
    """Scheduler-triggered: find due concepts and generate review prompts.
    Outputs REVIEW: lines for the bot to send as DMs."""
    db.init_databases()

    due = db.get_due_concepts(limit=5)
    if not due:
        return  # Nothing due, empty output

    concept = due[0]
    detail = db.get_concept_detail(concept['id'])
    if not detail:
        return

    topic_names = [t['title'] for t in detail.get('topics', [])]
    recent_reviews = detail.get('recent_reviews', [])
    remark_summary = detail.get('remark_summary', '')

    context_parts = [
        f"Concept: {detail['title']} (#{detail['id']})",
        f"Description: {detail.get('description', 'N/A')}",
        f"Topics: {', '.join(topic_names) if topic_names else 'untagged'}",
        f"Score: {detail['mastery_level']}/100, "
        f"Reviews: {detail['review_count']}",
    ]

    if remark_summary:
        context_parts.append(f"Latest remark: {remark_summary[:100]}")

    if recent_reviews:
        last = recent_reviews[0]
        context_parts.append(f"Last Q: {last.get('question_asked', 'N/A')}")
        context_parts.append(f"Last quality: {last.get('quality', 'N/A')}/5")

    context_str = " | ".join(context_parts)
    print(f"REVIEW: {concept['id']}|{context_str}")

    if len(due) > 1:
        remaining = len(due) - 1
        print(f"REVIEW_INFO: {remaining} more concept(s) due for review", file=sys.stderr)


def mode_maintenance():
    """Scheduler-triggered: run DB diagnostics and output issues for the LLM
    to triage. Outputs MAINT: lines — one per issue with suggested action."""
    db.init_databases()

    context = ctx.build_maintenance_context()

    # If no issues, output nothing (scheduler will skip DM)
    if "No issues found" in context:
        return

    # Output the full diagnostic context for the pipeline to send to the LLM
    print(f"MAINT: {context}")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Learning Agent CLI")
    parser.add_argument("--mode", choices=["command", "reply", "review-check", "maintenance"],
                        default="command", help="Execution mode")
    parser.add_argument("--input", default="", help="User input text")
    parser.add_argument("--context-only", action="store_true",
                        help="Only output dynamic context (step 1 of pipeline)")
    parser.add_argument("--fetch", default=None,
                        help="Execute a fetch query (JSON params string)")

    args = parser.parse_args()

    # Ensure DB is ready
    db.init_databases()

    if args.fetch:
        mode_fetch(args.fetch)
    elif args.context_only:
        mode_context_only(args.input, args.mode)
    elif args.mode == "review-check":
        mode_review_check()
    elif args.mode == "maintenance":
        mode_maintenance()
    elif args.mode == "reply":
        mode_reply(args.input)
    else:
        mode_command(args.input)


if __name__ == "__main__":
    main()
