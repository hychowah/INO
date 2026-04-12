#!/usr/bin/env python3
"""
Debug script — test the two-prompt scheduled quiz pipeline.

Usage:
  python scripts/test_quiz_generator.py --list-due             # pick a concept ID
    python scripts/test_quiz_generator.py                        # auto-pick top due concept
  python scripts/test_quiz_generator.py <concept_id>           # context + P1
  python scripts/test_quiz_generator.py <concept_id> --p2      # context + P1 + P2
  python scripts/test_quiz_generator.py <concept_id> --context-only  # just show context

Examples:
  python scripts/test_quiz_generator.py --list-due
    python scripts/test_quiz_generator.py
  python scripts/test_quiz_generator.py 12
  python scripts/test_quiz_generator.py 12 --p2
  python scripts/test_quiz_generator.py 12 --context-only
"""

import argparse
import asyncio
from datetime import datetime
import json
import sys
from pathlib import Path

# Ensure UTF-8 output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
from db import preferences
from services import context as ctx


LOG_DIR = Path(__file__).resolve().parent / "prompt_logs"
QUESTION_TYPES = {
    "definition",
    "mechanism",
    "comparison",
    "application",
    "synthesis",
    "edge-case",
    "teach-back",
}


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


def resolve_concept_id(concept_id: int | None) -> int | None:
    """Return the requested concept id or auto-pick the top due concept."""
    if concept_id is not None:
        return concept_id

    due = db.get_due_concepts(limit=1)
    if not due:
        print("No concepts due for review. Use --list-due to browse or pass a concept_id.")
        return None

    selected = due[0]
    print(f"Auto-selected concept #{selected['id']} - {selected['title']}")
    return selected["id"]


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


def validate_p1_result(result: dict) -> dict:
    """Validate the P1 response shape and return field-level status."""
    checks: dict[str, str] = {}

    def record(name: str, ok: bool, detail: str) -> None:
        checks[name] = f"{'PASS' if ok else 'FAIL'}: {detail}"

    question = result.get("question")
    record("question", isinstance(question, str) and bool(question.strip()), "non-empty string")

    formatted_question = result.get("formatted_question")
    record(
        "formatted_question",
        isinstance(formatted_question, str) and bool(formatted_question.strip()),
        "non-empty string",
    )

    difficulty = result.get("difficulty")
    record(
        "difficulty",
        isinstance(difficulty, int) and 0 <= difficulty <= 100,
        "integer in range 0-100",
    )

    question_type = result.get("question_type")
    record(
        "question_type",
        isinstance(question_type, str) and question_type in QUESTION_TYPES,
        f"one of {sorted(QUESTION_TYPES)}",
    )

    target_facet = result.get("target_facet")
    record(
        "target_facet",
        isinstance(target_facet, str) and bool(target_facet.strip()),
        "non-empty string",
    )

    reasoning = result.get("reasoning")
    record("reasoning", isinstance(reasoning, str) and bool(reasoning.strip()), "non-empty string")

    concept_ids = result.get("concept_ids")
    record(
        "concept_ids",
        isinstance(concept_ids, list)
        and bool(concept_ids)
        and all(isinstance(item, int) for item in concept_ids),
        "non-empty list[int]",
    )

    choices = result.get("choices")
    choices_ok = choices is None or (
        isinstance(choices, list)
        and bool(choices)
        and all(isinstance(item, str) and item.strip() for item in choices)
    )
    record("choices", choices_ok, "optional list[str]")
    return checks


def print_validation(checks: dict) -> bool:
    """Print validation results and return overall success."""
    print("\nValidation")
    print("-" * 60)
    ok = True
    for field, status in checks.items():
        print(f"{field:>18}: {status}")
        ok = ok and status.startswith("PASS")
    print(f"{'overall':>18}: {'PASS' if ok else 'FAIL'}")
    return ok


def build_log_payload(
    concept_id: int,
    context_text: str,
    persona_name: str,
    runs: list[dict],
    comparison: dict | None = None,
) -> dict:
    """Build structured JSON output for saved harness runs."""
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "concept_id": concept_id,
        "persona": persona_name,
        "context": context_text,
        "runs": runs,
        "comparison": comparison,
    }


def write_log(payload: dict) -> Path:
    """Write structured harness output to the prompt_logs directory."""
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = LOG_DIR / f"quiz_gen_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


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
    """Run the delivery-formatting stage and show output."""
    from services.pipeline import package_quiz_for_discord

    print("\n" + "=" * 60)
    print("DELIVERY OUTPUT")
    print("=" * 60)
    try:
        result = await package_quiz_for_discord(p1_result, concept_id)
        print(result)
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


async def run_format_quiz_action(p1_result: dict, concept_id: int):
    """Run deterministic packaging when available and show output."""
    try:
        from services.pipeline import format_quiz_action
    except ImportError:
        print(
            "format_quiz_action() not available yet; skipping deterministic packaging comparison."
        )
        return None

    print("\n" + "=" * 60)
    print("DETERMINISTIC PACKAGING OUTPUT")
    print("=" * 60)
    try:
        result = format_quiz_action(p1_result, concept_id)
        print(result)
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def with_persona_override(persona_name: str | None):
    """Context manager-like helper to temporarily switch persona for the harness."""

    class PersonaOverride:
        def __init__(self, override_name: str | None):
            self.override_name = override_name
            self.original_name: str | None = None

        def __enter__(self):
            self.original_name = preferences.get_persona()
            if self.override_name:
                preferences.set_persona(self.override_name)
            return preferences.get_persona()

        def __exit__(self, exc_type, exc, tb):
            if self.override_name and self.original_name:
                preferences.set_persona(self.original_name)
            return False

    return PersonaOverride(persona_name)


def main():
    parser = argparse.ArgumentParser(description="Test quiz question generator")
    parser.add_argument(
        "concept_id",
        nargs="?",
        type=int,
        help="Concept ID to generate question for (omit to auto-pick top due concept)",
    )
    parser.add_argument("--p2", action="store_true", help="Also run Prompt 2 (packaging)")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run Prompt 1 multiple times for the same concept (default: 1)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate Prompt 1 output fields after each run",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Write structured JSON output to scripts/prompt_logs/",
    )
    parser.add_argument(
        "--compare-p2",
        action="store_true",
        help="Run both Prompt 2 and deterministic packaging when available",
    )
    parser.add_argument(
        "--persona",
        choices=preferences.get_available_personas(),
        help="Temporarily override the active persona for this harness run",
    )
    parser.add_argument(
        "--context-only", action="store_true", help="Only show context, don't call LLM"
    )
    parser.add_argument("--list-due", action="store_true", help="List concepts due for review")
    args = parser.parse_args()

    db.init_databases()

    if args.list_due:
        list_due()
        return

    concept_id = resolve_concept_id(args.concept_id)
    if concept_id is None:
        return

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    with with_persona_override(args.persona) as active_persona:
        print(f"Active persona: {active_persona}")
        context_text = show_context(concept_id)

        if args.context_only:
            return

        async def run():
            runs: list[dict] = []
            p1_result: dict | None = None
            comparison: dict | None = None

            for index in range(args.repeat):
                if args.repeat > 1:
                    print(f"\nRun {index + 1}/{args.repeat}")
                p1_result = await run_p1(concept_id)
                checks = validate_p1_result(p1_result) if p1_result and args.validate else None
                if checks:
                    print_validation(checks)
                runs.append(
                    {
                        "run": index + 1,
                        "p1_result": p1_result,
                        "validation": checks,
                    }
                )

            if p1_result and args.p2:
                comparison = {"p2": await run_p2(p1_result, concept_id)}

            if p1_result and args.compare_p2:
                comparison = comparison or {}
                comparison["deterministic"] = await run_format_quiz_action(p1_result, concept_id)

            if args.log:
                out_path = write_log(
                    build_log_payload(concept_id, context_text, active_persona, runs, comparison)
                )
                print(f"\nSaved log to: {out_path}")

        asyncio.run(run())


if __name__ == "__main__":
    main()
