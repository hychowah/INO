"""
Manual maintenance and dedup smoke script.

Run from the learning_agent directory:
    python scripts/maintenance_smoke.py              # run both
    python scripts/maintenance_smoke.py --maint      # maintenance only
    python scripts/maintenance_smoke.py --dedup      # dedup only
    python scripts/maintenance_smoke.py --dry-run    # dedup without executing merges
    python scripts/maintenance_smoke.py --similarity # show similarity matrix from live DB

This file is intentionally not part of the automated pytest suite.
"""

import argparse
import asyncio
import logging

import db
from services import context as ctx
from services import pipeline


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)-10s %(message)s",
        datefmt="%H:%M:%S",
    )


def run_similarity_test():
    """Show live similarity matrix from actual DB concepts."""
    print("=" * 60)
    print("SIMILARITY MATRIX (live DB concepts)")
    print("=" * 60)
    concepts = db.get_all_concepts_summary()
    if len(concepts) < 2:
        print("  Not enough concepts to compare.\n")
        return True

    print(f"\n  {'':40s}", end="")
    for concept in concepts:
        print(f"  #{concept['id']:>3}", end="")
    print()

    flagged = []
    for left_index, left in enumerate(concepts):
        label = f"#{left['id']} {left['title'][:35]}"
        print(f"  {label:40s}", end="")
        for right_index, right in enumerate(concepts):
            if right_index <= left_index:
                print("     .", end="")
            else:
                similarity = db._title_similarity(left["title"], right["title"])
                marker = " *" if similarity >= 0.5 else "  "
                print(f"  {similarity:.2f}{marker}", end="")
                if similarity >= 0.5:
                    flagged.append((left, right, similarity))
        print()

    print("\n  * = similarity >= 0.5 (would be caught by dedup agent)")
    if flagged:
        print(f"\n  Flagged pairs ({len(flagged)}):")
        for left, right, similarity in flagged:
            print(
                f'    {similarity:.2f}  #{left["id"]} "{left["title"]}" ↔ #{right["id"]} "{right["title"]}"'
            )
    else:
        print("\n  No similar pairs found.")
    print()
    return True


def run_maintenance_test():
    """Run maintenance diagnostics and print the context that would be sent."""
    print("=" * 60)
    print("MAINTENANCE DIAGNOSTICS")
    print("=" * 60)

    maint_context = ctx.build_maintenance_context()
    print(maint_context)

    if "No issues found" in maint_context:
        print("\n  Result: HEALTHY — no issues to triage")
    else:
        issue_lines = [line for line in maint_context.split("\n") if line.startswith("- [")]
        print(f"\n  Result: {len(issue_lines)} issue(s) found")
    print()


async def run_dedup_test(dry_run: bool = False):
    """Run the dedup sub-agent and optionally execute merges."""
    print("=" * 60)
    print("DEDUP SUB-AGENT")
    print("=" * 60)

    concepts = db.get_all_concepts_summary()
    print(f"\nAll concepts ({len(concepts)}):")
    for concept in concepts:
        description = f" — {concept['description'][:60]}" if concept.get("description") else ""
        topics = f" [{concept['topic_names']}]" if concept.get("topic_names") else " [untagged]"
        print(f"  #{concept['id']}: {concept['title']}{description}{topics}")

    print("\nCalling LLM dedup agent...")
    groups = await pipeline.handle_dedup_check()

    if not groups:
        print("  No duplicates found by LLM.\n")
        return

    print(f"\n  Found {len(groups)} duplicate group(s):")
    for group in groups:
        merge_str = ", ".join(f"#{merge_id}" for merge_id in group["merge"])
        print(f"    KEEP #{group['keep']} ← merge {merge_str}  ({group.get('reason', '')})")

    if dry_run:
        print("\n  [DRY RUN] Skipping merges.\n")
        return

    print("\n  Executing merges...")
    summaries = await pipeline.execute_dedup_merges(groups)
    for summary in summaries:
        print(f"    ✓ {summary}")
    print(f"\n  Done — {len(summaries)} merge(s) executed.\n")


async def main():
    parser = argparse.ArgumentParser(description="Maintenance and dedup smoke script")
    parser.add_argument("--maint", action="store_true", help="Run maintenance only")
    parser.add_argument("--dedup", action="store_true", help="Run dedup only")
    parser.add_argument(
        "--dry-run", action="store_true", help="Dedup: identify dupes but don't merge"
    )
    parser.add_argument(
        "--similarity", action="store_true", help="Show similarity matrix from live DB concepts"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)

    db.init_databases()
    pipeline.init_databases()

    if args.similarity:
        ok = run_similarity_test()
        raise SystemExit(0 if ok else 1)

    run_maint = args.maint or (not args.maint and not args.dedup)
    run_dedup = args.dedup or (not args.maint and not args.dedup)

    if run_maint:
        run_maintenance_test()

    if run_dedup:
        await run_dedup_test(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
