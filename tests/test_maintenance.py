"""
Test script for maintenance and dedup agents.
Run from the learning_agent directory:
    python tests/test_maintenance.py              # run both
    python tests/test_maintenance.py --maint      # maintenance only
    python tests/test_maintenance.py --dedup      # dedup only
    python tests/test_maintenance.py --dry-run    # dedup without executing merges
    python tests/test_maintenance.py --similarity # show similarity matrix from live DB
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure we can import from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

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

    # Print header
    print(f"\n  {'':40s}", end="")
    for c in concepts:
        print(f"  #{c['id']:>3}", end="")
    print()

    flagged = []
    for i, a in enumerate(concepts):
        label = f"#{a['id']} {a['title'][:35]}"
        print(f"  {label:40s}", end="")
        for j, b in enumerate(concepts):
            if j <= i:
                print("     .", end="")
            else:
                sim = db._title_similarity(a["title"], b["title"])
                marker = " *" if sim >= 0.5 else "  "
                print(f"  {sim:.2f}{marker}", end="")
                if sim >= 0.5:
                    flagged.append((a, b, sim))
        print()

    print("\n  * = similarity >= 0.5 (would be caught by dedup agent)")
    if flagged:
        print(f"\n  Flagged pairs ({len(flagged)}):")
        for a, b, sim in flagged:
            print(f'    {sim:.2f}  #{a["id"]} "{a["title"]}" ↔ #{b["id"]} "{b["title"]}"')
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
        issue_lines = [ln for ln in maint_context.split("\n") if ln.startswith("- [")]
        print(f"\n  Result: {len(issue_lines)} issue(s) found")
    print()


async def run_dedup_test(dry_run: bool = False):
    """Run the dedup sub-agent and optionally execute merges."""
    print("=" * 60)
    print("DEDUP SUB-AGENT")
    print("=" * 60)

    # Show concept list
    concepts = db.get_all_concepts_summary()
    print(f"\nAll concepts ({len(concepts)}):")
    for c in concepts:
        desc = f" — {c['description'][:60]}" if c.get("description") else ""
        topics = f" [{c['topic_names']}]" if c.get("topic_names") else " [untagged]"
        print(f"  #{c['id']}: {c['title']}{desc}{topics}")

    print("\nCalling LLM dedup agent...")
    groups = await pipeline.handle_dedup_check()

    if not groups:
        print("  No duplicates found by LLM.\n")
        return

    print(f"\n  Found {len(groups)} duplicate group(s):")
    for g in groups:
        merge_str = ", ".join(f"#{m}" for m in g["merge"])
        print(f"    KEEP #{g['keep']} ← merge {merge_str}  ({g.get('reason', '')})")

    if dry_run:
        print("\n  [DRY RUN] Skipping merges.\n")
        return

    print("\n  Executing merges...")
    summaries = await pipeline.execute_dedup_merges(groups)
    for s in summaries:
        print(f"    ✓ {s}")
    print(f"\n  Done — {len(summaries)} merge(s) executed.\n")


async def main():
    parser = argparse.ArgumentParser(description="Test maintenance & dedup agents")
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

    # Initialize
    db.init_databases()
    pipeline.init_databases()

    if args.similarity:
        ok = run_similarity_test()
        sys.exit(0 if ok else 1)

    # Default: run both unless one is specified
    run_maint = args.maint or (not args.maint and not args.dedup)
    run_ded = args.dedup or (not args.maint and not args.dedup)

    if run_maint:
        run_maintenance_test()

    if run_ded:
        await run_dedup_test(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
