"""
Dedup sub-agent — finds and merges duplicate concepts via LLM.
See DEVNOTES.md §2.2 for background.
"""

import json
import logging
import re

import config
import db
from db.reviews import REMARK_SUMMARY_MAX
from services.parser import _extract_json_object

logger = logging.getLogger("dedup")


def _regenerate_remark_summary(concept_id: int):
    """Rebuild remark_summary cache from the latest concept_remarks rows."""
    remarks = db.get_remarks(concept_id, limit=5)
    if remarks:
        summary = "\n---\n".join(r['content'] for r in remarks)
        if len(summary) > REMARK_SUMMARY_MAX:
            summary = summary[:REMARK_SUMMARY_MAX - 15] + "\n…[truncated]"
        conn = db._conn()
        conn.execute(
            "UPDATE concepts SET remark_summary = ?, remark_updated_at = ? WHERE id = ?",
            (summary, db._now_iso(), concept_id)
        )
        conn.commit()
        conn.close()


async def handle_dedup_check() -> list[dict] | None:
    """Dedicated dedup sub-agent: sends a focused prompt with just the concept
    list to the LLM, asks it to identify semantic duplicates.

    Returns a list of duplicate groups like:
      [{"keep": 26, "merge": [24, 25], "reason": "All about bootloaders"}]
    or None if no duplicates found.
    """
    from services.llm import get_provider, LLMError

    concepts = db.get_all_concepts_summary()
    if len(concepts) < 2:
        return None

    lines = []
    for c in concepts:
        desc = f" — {c['description'][:80]}" if c.get('description') else ""
        topics = f" [{c['topic_names']}]" if c.get('topic_names') else " [untagged]"
        lines.append(f"  #{c['id']}: {c['title']}{desc}{topics} "
                     f"(reviews: {c['review_count']}, score: {c['mastery_level']}/100)")

    concept_list = "\n".join(lines)

    prompt = f"""You are a dedup agent for a learning system. Your ONLY job is to find TRUE duplicates — concepts that are the SAME thing with different wording.

## All Concepts
{concept_list}

## Instructions
1. Find concepts that are **genuinely the same subject** — just phrased differently.
2. For each duplicate group, pick the ONE concept to KEEP — prefer the one with more reviews, then the most specific/descriptive title.
3. List which concepts should be merged INTO the kept one.

## CRITICAL: What is NOT a duplicate
- Concepts under the same topic that cover **different facets** are NOT duplicates
- A specific technique and a broader practice that uses it are NOT duplicates
- A sub-topic and its parent concept are NOT duplicates
- Concepts that are merely **related** but teach different things are NOT duplicates

**Examples of TRUE duplicates (merge these):**
- "Covariance" and "Covariance — How Two Variables Change Together" → same concept, different titles
- "304 vs 316 Steel Grades" and "Stainless Steel 304 vs 316 Comparison" → same comparison, rephrased

**Examples of NOT duplicates (do NOT merge):**
- "Ring Buffer Lock-Free Pattern" and "ISR Bottom Half Pattern" → different techniques, even if related
- "Reset Vector & Memory Layout" and "Embedded Bootloader" → specific vs broad, different learning goals
- "Chi-Square Test" and "Covariance" → different statistical concepts
- "VIE Structure" and "Hong Kong Listed VIE Stocks" → general concept vs specific application

**When in doubt, do NOT merge.** It is far better to keep two similar concepts separate than to merge concepts that cover different learning goals. The user needs granular concepts for effective spaced repetition.

## Output Format
Respond with ONLY a JSON array. If no duplicates found (the common case), respond with `[]`.

```json
[
  {{
    "keep": <concept_id to keep>,
    "merge": [<concept_ids to delete>],
    "reason": "brief explanation of why these are the SAME concept"
  }}
]
```

No other text. Just the JSON array."""

    logger.info(f"[DEDUP] Running dedup check on {len(concepts)} concepts")

    provider = get_provider()
    try:
        raw = await provider.send(
            prompt,
            session=None,
            timeout=config.COMMAND_TIMEOUT,
        )
    except LLMError as e:
        logger.error(f"[DEDUP] LLM error: {e}")
        return None

    logger.debug(f"[DEDUP] Raw output: {raw[:500]}")

    groups = _parse_dedup_response(raw)
    if not groups:
        logger.info("[DEDUP] No duplicates found")
        return None

    logger.info(f"[DEDUP] Found {len(groups)} duplicate group(s)")
    return groups


def _parse_dedup_response(raw: str) -> list[dict] | None:
    """Parse the dedup agent's JSON array response."""
    code_block = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?\s*```', raw)
    if code_block:
        raw = code_block.group(1).strip()

    arr_match = re.search(r'\[[\s\S]*\]', raw)
    if not arr_match:
        return None

    try:
        groups = json.loads(arr_match.group())
        if not isinstance(groups, list):
            return None
        valid = []
        for g in groups:
            if isinstance(g, dict) and 'keep' in g and 'merge' in g:
                valid.append({
                    'keep': int(g['keep']),
                    'merge': [int(x) for x in g['merge']],
                    'reason': g.get('reason', ''),
                })
        return valid if valid else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


async def execute_dedup_merges(groups: list[dict]) -> list[str]:
    """Execute the dedup agent's merge recommendations.
    For each group: merge remarks into keep target, then delete duplicates.
    Returns a list of summary strings."""
    summaries = []
    for g in groups:
        keep_id = g['keep']
        merge_ids = g['merge']
        keep_concept = db.get_concept(keep_id)

        if not keep_concept:
            logger.warning(f"[DEDUP] Keep target #{keep_id} not found, skipping")
            continue

        merged_titles = []
        for mid in merge_ids:
            merge_concept = db.get_concept(mid)
            if not merge_concept:
                continue

            detail = db.get_concept_detail(mid)
            if detail and detail.get('remarks'):
                for remark in detail['remarks']:
                    db.add_remark(keep_id,
                                  f"[merged from #{mid} '{merge_concept['title']}'] "
                                  f"{remark['content']}")

            db.delete_concept(mid)
            merged_titles.append(f"#{mid} \"{merge_concept['title']}\"")
            logger.info(f"[DEDUP] Merged #{mid} into #{keep_id}")

        # Regenerate remark_summary for the keep target after all merges
        if merged_titles:
            _regenerate_remark_summary(keep_id)

        if merged_titles:
            summary = (f"Merged {', '.join(merged_titles)} → "
                       f"#{keep_id} \"{keep_concept['title']}\" "
                       f"({g.get('reason', '')})")
            summaries.append(summary)

    return summaries


def format_dedup_suggestions(groups: list[dict]) -> str:
    """Format dedup groups into a human-readable Discord message.
    Each group shows which concept would be kept/deleted with context."""
    if not groups:
        return "No duplicates found."

    lines = []
    for i, g in enumerate(groups, 1):
        keep_id = g['keep']
        keep_concept = db.get_concept(keep_id)
        keep_title = keep_concept['title'] if keep_concept else f"#{keep_id}"
        keep_score = keep_concept.get('mastery_level', '?') if keep_concept else '?'
        keep_reviews = keep_concept.get('review_count', '?') if keep_concept else '?'

        delete_parts = []
        for mid in g['merge']:
            mc = db.get_concept(mid)
            if mc:
                delete_parts.append(
                    f"  Delete **{mc['title']}** (score {mc.get('mastery_level', '?')}, "
                    f"{mc.get('review_count', '?')} reviews)"
                )
            else:
                delete_parts.append(f"  Delete concept #{mid} (not found)")

        lines.append(
            f"**{i}.** Keep **{keep_title}** (score {keep_score}, {keep_reviews} reviews)\n"
            + "\n".join(delete_parts)
            + f"\n  → {g.get('reason', 'Similar concepts')}"
        )

    header = ("🔄 **Potential Duplicate Concepts** ({} group(s))\n\n"
              "Review and approve/reject each merge below.\n"
              "These suggestions expire in 24 hours.\n\n").format(len(groups))
    return header + "\n\n".join(lines)