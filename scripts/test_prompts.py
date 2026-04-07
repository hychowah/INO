#!/usr/bin/env python3
"""
Manual prompt inspection script.

Shows the EXACT system prompt + user prompt sent to the LLM, calls the LLM
with real tokens, then shows the raw output.  Useful for debugging what the
model actually sees before/after a message is sent.

Usage:
    python scripts/test_prompts.py maintenance
    python scripts/test_prompts.py reorganize
    python scripts/test_prompts.py quiz                   # auto-picks top due concept
    python scripts/test_prompts.py quiz --concept-id 12
    python scripts/test_prompts.py quiz --list            # list concepts to pick from
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import db
from services import context as ctx
from services.llm import get_provider
from services.pipeline import (
    MAX_MAINTENANCE_ACTIONS,
    MAX_TAXONOMY_ACTIONS,
    build_system_prompt,
    call_taxonomy_loop,
    handle_taxonomy,
)

# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

SEP = "=" * 72
SEP_THIN = "-" * 72


def _section(title: str, content: str) -> None:
    """Print a clearly labelled section with char/token estimate."""
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    print(content)
    tok = len(content) // 4
    print(f"\n{SEP_THIN}")
    print(f"  {len(content):,} chars  /  ~{tok:,} tokens")
    print(SEP_THIN)


def _build_full_prompt(mode: str, text: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) assembled identically to _call_llm()."""
    system_prompt = build_system_prompt(mode=mode)
    dynamic_context = ctx.build_prompt_context(text, mode, is_new_session=True)
    user_prompt = (
        f"{dynamic_context}\n\n"
        f'IMPORTANT — the user said: "{text}"\n'
        f"Process this request RIGHT NOW using the response format defined in the "
        f"system prompt (JSON action block, FETCH action, ASK:, or REPLY:). "
        f"Do not describe your instructions."
    )
    return system_prompt, user_prompt


async def _call_and_print(
    system_prompt: str,
    user_prompt: str,
    session_name: str,
) -> None:
    """Send to LLM and print the raw output."""
    provider = get_provider()
    provider.clear_session(session_name)

    print(f"\n{SEP}")
    print("  → Calling LLM …")
    print(SEP)

    try:
        raw = await provider.send(
            user_prompt,
            session=session_name,
            system_prompt=system_prompt,
            timeout=config.COMMAND_TIMEOUT,
        )
    except Exception as exc:
        print(f"\n❌  LLM error: {exc}")
        return
    finally:
        provider.clear_session(session_name)

    _section("LLM OUTPUT  (raw, before action extraction)", raw)


# ─────────────────────────────────────────────────────────────────────────────
# Maintenance mode
# ─────────────────────────────────────────────────────────────────────────────

_MAINTENANCE_PREAMBLE = (
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


async def run_maintenance() -> None:
    """Show the maintenance prompt (first LLM call) and its raw response."""
    print("\n🔧  MAINTENANCE MODE — Prompt Inspection")

    # Build the diagnostic context (same path as handle_maintenance)
    maint_context = ctx.build_maintenance_context()
    if "No issues found" in maint_context:
        print(
            "\n  ℹ️  No maintenance issues found in the current DB.  "
            "Showing the prompt anyway — the LLM will receive an all-clear context.\n"
        )

    # Assemble the text that call_action_loop sends as its first message
    action_text = (
        f"[MAINTENANCE] {_MAINTENANCE_PREAMBLE}\n\n"
        f"{maint_context}\n\n"
        f"You may execute up to {MAX_MAINTENANCE_ACTIONS} actions this run. "
        f"Output one JSON action at a time. After each, you'll see the result "
        f"and can output another action or a final REPLY: summary."
    )

    system_prompt, user_prompt = _build_full_prompt("maintenance", action_text)

    _section("SYSTEM PROMPT  (core + maintenance + knowledge skills + persona + prefs)", system_prompt)
    _section("USER PROMPT  (dynamic context + diagnostic report + action budget)", user_prompt)

    await _call_and_print(system_prompt, user_prompt, session_name="test_maintenance_prompt")


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy reorganization mode
# ─────────────────────────────────────────────────────────────────────────────

_TAXONOMY_PREAMBLE = (
    "Analyze this topic tree and improve its hierarchy for clarity and scannability.\n\n"
    "**Safe to execute:** add_topic (create grouping parents), link_topics (nest topics).\n"
    "**Propose for approval:** update_topic (rename), unlink_topics, delete_topic, "
    "unlink_concept.\n\n"
    "**NEVER** modify mastery_level, interval_days, next_review_at, ease_factor, or "
    "review_count. Do NOT re-propose renames listed in the \u26d4 Suppressed Renames section."
)


async def run_reorganize() -> None:
    """Show the taxonomy reorganization prompt then run the full action loop."""
    print("\n\U0001f333  REORGANIZE MODE \u2014 Full Loop Inspection")

    taxonomy_context = handle_taxonomy()
    if taxonomy_context is None:
        print(
            "\n  \u2139\ufe0f  No topics found in the current DB.  "
            "Add some topics before running reorganize."
        )
        return

    action_text = (
        f"[TAXONOMY-MODE] {_TAXONOMY_PREAMBLE}\n\n"
        f"{taxonomy_context}\n\n"
        f"You may execute up to {MAX_TAXONOMY_ACTIONS} actions this run. "
        f"Output one JSON action at a time. After each, you'll see the result "
        f"and can output another action or a final REPLY: summary."
    )

    system_prompt, user_prompt = _build_full_prompt("taxonomy-mode", action_text)

    _section("SYSTEM PROMPT  (taxonomy skill + persona + prefs)", system_prompt)
    _section("USER PROMPT  (taxonomy context + action budget)", user_prompt)

    print(f"\n{SEP}")
    print("  \u2192 Running full taxonomy action loop\u2026")
    print(SEP)

    report_text, proposed_actions = await call_taxonomy_loop(taxonomy_context)

    _section("LOOP RESULT  (final REPLY summary)", report_text)

    if proposed_actions:
        proposed_str = "\n".join(
            f"  [{i + 1}] {a.get('action', '?')} \u2014 {a.get('message', '')[:120]}"
            for i, a in enumerate(proposed_actions)
        )
        _section(f"PROPOSED ACTIONS  ({len(proposed_actions)} pending user approval)", proposed_str)
    else:
        print(f"\n{SEP_THIN}")
        print("  (no actions proposed for approval)")
        print(SEP_THIN)


# ─────────────────────────────────────────────────────────────────────────────
# Interactive quiz mode
# ─────────────────────────────────────────────────────────────────────────────

def _list_concepts() -> None:
    """Print a concept table so the user can pick an ID."""
    due = db.get_due_concepts(limit=20)
    pool = due if due else db.search_concepts("", limit=20)
    if not pool:
        print("No concepts found in DB.")
        return
    label = "due concepts" if due else "all concepts (none due)"
    print(f"\n  Showing {label}:\n")
    print(f"  {'ID':>5}  {'Score':>5}  {'Reviews':>7}  Title")
    print(f"  {'-'*5}  {'-'*5}  {'-'*7}  {'-'*35}")
    for c in pool:
        print(
            f"  {c['id']:>5}  "
            f"{c.get('mastery_level', 0):>5}  "
            f"{c.get('review_count', 0):>7}  "
            f"{c['title']}"
        )
    print()


async def run_quiz(concept_id: int | None) -> None:
    """Show the interactive quiz prompt and first LLM response for a concept."""
    # Auto-pick the top due concept if none specified
    if concept_id is None:
        due = db.get_due_concepts(limit=1)
        if not due:
            print(
                "\n  No concepts due for review.  "
                "Use --concept-id N to specify one, or --list to browse."
            )
            return
        concept_id = due[0]["id"]
        print(f"\n  (Auto-selected: concept #{concept_id} — {due[0]['title']})")

    concept = db.get_concept(concept_id)
    if not concept:
        print(f"\n  Concept #{concept_id} not found in DB.")
        return

    print(f"\n🧠  QUIZ MODE — Prompt Inspection  (#{concept_id}: {concept['title']})")

    # Mirror the interactive flow: user says "quiz me on <title>"
    # pipeline.call_with_fetch_loop(mode="command", text="quiz me on X")
    quiz_text = f"quiz me on: {concept['title']}"

    # Pre-set active concept so context builder includes concept detail
    db.set_session("active_concept_id", str(concept_id))

    try:
        system_prompt, user_prompt = _build_full_prompt("command", quiz_text)

        _section("SYSTEM PROMPT  (core + quiz + knowledge skills + persona + prefs)", system_prompt)
        _section("USER PROMPT  (dynamic context + quiz request)", user_prompt)

        await _call_and_print(system_prompt, user_prompt, session_name="test_quiz_prompt")
    finally:
        db.set_session("active_concept_id", None)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect raw LLM prompts and responses for maintenance / quiz modes.\n"
            "Uses your local .env credentials — real tokens will be consumed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("maintenance", help="Maintenance mode: show prompt + call LLM")
    sub.add_parser("reorganize", help="Taxonomy reorganize mode: show prompt + call LLM")

    quiz_p = sub.add_parser("quiz", help="Interactive quiz mode: show prompt + call LLM")
    quiz_p.add_argument(
        "--concept-id",
        type=int,
        metavar="ID",
        help="Concept ID to quiz on (omit to auto-pick top due concept)",
    )
    quiz_p.add_argument(
        "--list",
        action="store_true",
        help="List available/due concepts and exit (no LLM call)",
    )

    args = parser.parse_args()

    db.init_databases()

    # --list just prints a short table — keep it in the terminal
    if args.cmd == "quiz" and args.list:
        _list_concepts()
        return

    # All other modes produce long output — write to a timestamped file
    log_dir = Path(__file__).resolve().parent / "prompt_logs"
    log_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.cmd == "quiz":
        cid = getattr(args, "concept_id", None)
        label = f"quiz_cid{cid}" if cid else "quiz"
    else:
        label = args.cmd  # "maintenance" or "reorganize"
    out_path = log_dir / f"prompts_{label}_{stamp}.txt"

    real_stdout = sys.stdout
    real_stdout.write(f"Writing output to: {out_path}\n")
    real_stdout.flush()

    with open(out_path, "w", encoding="utf-8") as fh:
        sys.stdout = fh
        try:
            if args.cmd == "maintenance":
                asyncio.run(run_maintenance())
            elif args.cmd == "reorganize":
                asyncio.run(run_reorganize())
            elif args.cmd == "quiz":
                asyncio.run(run_quiz(getattr(args, "concept_id", None)))
        finally:
            sys.stdout = real_stdout

    real_stdout.write(f"Done. Saved to: {out_path}\n")


if __name__ == "__main__":
    main()
