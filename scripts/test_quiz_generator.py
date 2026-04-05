#!/usr/bin/env python3
"""
Debug script — test the two-prompt scheduled quiz pipeline.

Usage:
  python scripts/test_quiz_generator.py --list-due             # pick a concept ID
  python scripts/test_quiz_generator.py <concept_id>           # context + P1
  python scripts/test_quiz_generator.py <concept_id> --p2      # context + P1 + P2
  python scripts/test_quiz_generator.py <concept_id> --context-only  # just show context

Examples:
  python scripts/test_quiz_generator.py --list-due
  python scripts/test_quiz_generator.py 12
  python scripts/test_quiz_generator.py 12 --p2
  python scripts/test_quiz_generator.py 12 --context-only
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure UTF-8 output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
from services import context as ctx


def list_due():
    """Print due concepts so the user can pick an ID."""
    due = db.get_due_concepts(limit=10)
    if not due:
        print("No concepts due for review.")
        return
    print(f"\n{'ID':>5}  {'Score':>5}  {'Reviews':>7}  Title")
    print("-" * 60)
    for c in due:
        print(f"{c['id']:>5}  {c['mastery_level']:>5}  {c['review_count']:>7}  {c['title']}")
    print()


def show_context(concept_id: int):
    """Show what data Prompt 1 would receive."""
    result = ctx.build_quiz_generator_context(concept_id)
    if not result:
        print(f"ERROR: Concept #{concept_id} not found")
        sys.exit(1)
    print("=" * 60)
    print("PROMPT 1 CONTEXT (pre-loaded data)")
    print("=" * 60)
    print(result)
    print(f"\n({len(result)} chars, ~{len(result) // 4} tokens)")
    return result


async def run_p1(concept_id: int):
    """Run Prompt 1 (reasoning model) and show output."""
    from services.pipeline import generate_quiz_question

    print("\n" + "=" * 60)
    print("PROMPT 1 OUTPUT (reasoning model)")
    print("=" * 60)
    try:
        result = await generate_quiz_question(concept_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


async def run_p2(p1_result: dict, concept_id: int):
    """Run Prompt 2 (packaging) and show output."""
    from services.pipeline import package_quiz_for_discord

    print("\n" + "=" * 60)
    print("PROMPT 2 OUTPUT (packaging model)")
    print("=" * 60)
    try:
        result = await package_quiz_for_discord(p1_result, concept_id)
        print(result)
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Test quiz question generator")
    parser.add_argument(
        "concept_id", nargs="?", type=int, help="Concept ID to generate question for"
    )
    parser.add_argument("--p2", action="store_true", help="Also run Prompt 2 (packaging)")
    parser.add_argument(
        "--context-only", action="store_true", help="Only show context, don't call LLM"
    )
    parser.add_argument("--list-due", action="store_true", help="List concepts due for review")
    args = parser.parse_args()

    db.init_db()

    if args.list_due:
        list_due()
        return

    if not args.concept_id:
        parser.error("concept_id is required (or use --list-due)")

    show_context(args.concept_id)

    if args.context_only:
        return

    async def run():
        p1_result = await run_p1(args.concept_id)
        if p1_result and args.p2:
            await run_p2(p1_result, args.concept_id)

    asyncio.run(run())


if __name__ == "__main__":
    main()
