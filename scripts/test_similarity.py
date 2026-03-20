"""
Vector similarity test harness.

Embeds a configurable set of concept pairs and shows cosine similarity scores.
Useful for tuning SIMILARITY_THRESHOLD_DEDUP and SIMILARITY_THRESHOLD_RELATION
before deploying real data.

Usage:
    python scripts/test_similarity.py              # run default test sets
    python scripts/test_similarity.py --group steel  # run only one group
    python scripts/test_similarity.py --list         # list available groups

Add your own groups at the bottom of this file in TEST_SETS.
"""

import argparse
import math
import sys
import textwrap
from pathlib import Path

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============================================================================
# Configurable test sets
# Each group is { "name": str, "items": [(label_a, text_a, label_b, text_b), ...] }
# text = what gets embedded — combine title + description like the real system does
# ============================================================================

TEST_SETS = [
    {
        "name": "steel",
        "description": "Stainless steel grades and related metals",
        "items": [
            (
                "Stainless Steel",
                "Stainless Steel — Iron alloy containing at least 10.5% chromium, resistant to corrosion and oxidation",
                "304 Stainless Steel",
                "304 Stainless Steel — Most common austenitic grade, 18% chromium 8% nickel, good weldability and formability",
            ),
            (
                "304",
                "304 Stainless Steel — Most common austenitic grade, 18% chromium 8% nickel, good weldability and formability",
                "Stainless Steel",
                "316 Stainless Steel — Austenitic grade with added molybdenum for improved chloride corrosion resistance",
            ),
            (
                "304 Stainless Steel",
                "304 Stainless Steel — Most common austenitic grade, 18% chromium 8% nickel, good weldability and formability",
                "Carbon Steel",
                "Carbon Steel — Steel alloy where carbon is the primary alloying element, stronger but less corrosion resistant",
            ),
            (
                "Stainless Steel",
                "Stainless Steel — Iron alloy containing at least 10.5% chromium, resistant to corrosion and oxidation",
                "Carbon Steel",
                "Carbon Steel — Steel alloy where carbon is the primary alloying element, stronger but less corrosion resistant",
            ),
            (
                "316 Stainless Steel",
                "316 Stainless Steel — Austenitic grade with added molybdenum for improved chloride corrosion resistance",
                "Carbon Steel",
                "Carbon Steel — Steel alloy where carbon is the primary alloying element, stronger but less corrosion resistant",
            ),
            (
                "304 Stainless Steel",
                "304 Stainless Steel — Most common austenitic grade, 18% chromium 8% nickel, good weldability and formability",
                "Python decorators",
                "Python decorators — Syntax for wrapping functions with additional behaviour using @syntax",
            ),
        ],
    },
    {
        "name": "dedup",
        "description": "Near-duplicate concept pairs (should trigger dedup guard at 0.92)",
        "items": [
            (
                "Welding",
                "Welding — Process of joining metals by melting and fusing them together using heat",
                "Welding Process",
                "Welding Process — Process of joining metals by melting and fusing them together using heat",
            ),
            (
                "MIG Welding",
                "MIG Welding — Metal inert gas welding using a continuous wire electrode",
                "MIG Welding (GMAW)",
                "MIG Welding (GMAW) — Metal inert gas welding, also called gas metal arc welding, uses continuous wire",
            ),
            (
                "TIG Welding",
                "TIG Welding — Tungsten inert gas welding, uses non-consumable tungsten electrode",
                "MIG Welding",
                "MIG Welding — Metal inert gas welding using a continuous wire electrode",
            ),
            (
                "Yield Strength",
                "Yield Strength — Stress at which a material begins to deform plastically",
                "Tensile Strength",
                "Tensile Strength — Maximum stress a material can withstand before fracture",
            ),
        ],
    },
    {
        "name": "relation",
        "description": "Related concept pairs (should cluster together at 0.5 threshold)",
        "items": [
            (
                "Corrosion Resistance",
                "Corrosion Resistance — Ability of a material to withstand degradation due to chemical reactions with environment",
                "Stainless Steel",
                "Stainless Steel — Iron alloy containing at least 10.5% chromium, resistant to corrosion and oxidation",
            ),
            (
                "Heat Treatment",
                "Heat Treatment — Controlled heating and cooling processes to alter material properties",
                "Annealing",
                "Annealing — Heat treatment that softens metal by heating then slowly cooling to relieve internal stresses",
            ),
            (
                "Weld Joint Design",
                "Weld Joint Design — Engineering decisions about joint geometry, fit-up, and preparation for welding",
                "Welding",
                "Welding — Process of joining metals by melting and fusing them together using heat",
            ),
            (
                "Passivation",
                "Passivation — Chemical treatment of stainless steel surface to remove iron contamination and restore oxide layer",
                "Corrosion Resistance",
                "Corrosion Resistance — Ability of a material to withstand degradation due to chemical reactions with environment",
            ),
        ],
    },
    {
        "name": "unrelated",
        "description": "Clearly unrelated pairs (should score below 0.3)",
        "items": [
            (
                "304 Stainless Steel",
                "304 Stainless Steel — Most common austenitic grade, 18% chromium 8% nickel",
                "Python generators",
                "Python generators — Functions that use yield to lazily produce values one at a time",
            ),
            (
                "Welding",
                "Welding — Process of joining metals by melting and fusing them together using heat",
                "Machine Learning",
                "Machine Learning — Algorithms that learn patterns from data without explicit programming",
            ),
            (
                "Tensile Strength",
                "Tensile Strength — Maximum stress a material can withstand before fracture",
                "Database indexing",
                "Database indexing — Data structures that improve query speed by providing fast lookup paths",
            ),
        ],
    },
    # -----------------------------------------------------------------------
    # ADD YOUR OWN GROUPS HERE
    # Copy the template below and fill in your concept pairs:
    #
    # {
    #     "name": "my_group",
    #     "description": "What I'm testing",
    #     "items": [
    #         (
    #             "Label A",
    #             "Label A — description of concept A",
    #             "Label B",
    #             "Label B — description of concept B",
    #         ),
    #     ],
    # },
    # -----------------------------------------------------------------------
]


# ============================================================================
# Similarity helpers
# ============================================================================

def cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_embed_fn():
    """Load the real embedding function from services.embeddings."""
    try:
        from services.embeddings import embed_text
        # Trigger model load now so timing is clear
        print("Loading model... (first call downloads ~420MB if not cached)")
        embed_text("warmup")
        print("Model ready.\n")
        return embed_text
    except Exception as e:
        print(f"ERROR: Could not load embedding model: {e}")
        print("Make sure sentence-transformers is installed:")
        print("  pip install sentence-transformers")
        sys.exit(1)


# ============================================================================
# Display helpers
# ============================================================================

THRESHOLDS = {
    "DEDUP (0.92)": 0.92,
    "RELATION (0.50)": 0.50,
}

def _bar(score: float, width: int = 30) -> str:
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


def _classify(score: float) -> str:
    if score >= 0.92:
        return "⚠ DEDUP RISK"
    elif score >= 0.75:
        return "● very similar"
    elif score >= 0.50:
        return "◉ related"
    elif score >= 0.25:
        return "○ loose link"
    else:
        return "  unrelated"


def run_group(group: dict, embed_fn) -> list:
    """Run all pairs in a group. Returns list of (label_a, label_b, score)."""
    name = group["name"]
    desc = group["description"]
    items = group["items"]

    print(f"{'═'*70}")
    print(f"  GROUP: {name.upper()}  —  {desc}")
    print(f"{'═'*70}")

    results = []
    for label_a, text_a, label_b, text_b in items:
        vec_a = embed_fn(text_a)
        vec_b = embed_fn(text_b)
        score = cosine_similarity(vec_a, vec_b)
        results.append((label_a, label_b, score))

        short_a = textwrap.shorten(label_a, 28, placeholder="…")
        short_b = textwrap.shorten(label_b, 28, placeholder="…")
        bar = _bar(score)
        cls = _classify(score)

        print(f"  {short_a:<28}  vs  {short_b:<28}")
        print(f"  Score: {score:.4f}  {bar}  {cls}")
        print()

    return results


def print_summary(all_results: list):
    print(f"{'═'*70}")
    print("  SUMMARY")
    print(f"{'═'*70}")
    print(f"  {'Label A':<28}  {'Label B':<28}  {'Score':>7}  Classification")
    print(f"  {'-'*28}  {'-'*28}  {'-'*7}  {'-'*14}")
    for label_a, label_b, score in sorted(all_results, key=lambda r: -r[2]):
        short_a = textwrap.shorten(label_a, 28, placeholder="…")
        short_b = textwrap.shorten(label_b, 28, placeholder="…")
        cls = _classify(score)
        print(f"  {short_a:<28}  {short_b:<28}  {score:.4f}  {cls}")
    print()
    print("  Thresholds in use:")
    for label, val in THRESHOLDS.items():
        print(f"    {label}: {val}")
    print()


# ============================================================================
# Entry point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Test vector similarity between concept pairs")
    parser.add_argument("--group", help="Run only this group name")
    parser.add_argument("--list", action="store_true", help="List available groups and exit")
    args = parser.parse_args()

    if args.list:
        print("Available groups:")
        for g in TEST_SETS:
            print(f"  {g['name']:<20} {g['description']}")
        return

    groups_to_run = TEST_SETS
    if args.group:
        groups_to_run = [g for g in TEST_SETS if g["name"] == args.group]
        if not groups_to_run:
            print(f"Group '{args.group}' not found. Use --list to see available groups.")
            sys.exit(1)

    embed_fn = load_embed_fn()

    all_results = []
    for group in groups_to_run:
        results = run_group(group, embed_fn)
        all_results.extend(results)

    if len(groups_to_run) > 1:
        print_summary(all_results)


if __name__ == "__main__":
    main()
