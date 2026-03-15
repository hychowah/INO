"""
Dedup sub-agent — finds and merges duplicate concepts via LLM.
See DEVNOTES.md §2.2 for background.
"""

import json
import logging
import re

import config
import db
from services.parser import _extract_json_object

logger = logging.getLogger("dedup")


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

    prompt = f"""You are a dedup agent for a learning system. Your ONLY job is to find duplicate or highly overlapping concepts that should be merged.

## All Concepts
{concept_list}

## Instructions
1. Find concepts that cover the SAME subject (different wording, same meaning).
2. For each duplicate group, pick the ONE concept to KEEP — prefer the one with more reviews, or the most descriptive title.
3. List which concepts should be merged INTO the kept one.
4. Ignore concepts that are merely related but cover different aspects.

## Output Format
Respond with ONLY a JSON array. If no duplicates found, respond with `[]`.

```json
[
  {{
    "keep": <concept_id to keep>,
    "merge": [<concept_ids to delete>],
    "reason": "brief explanation"
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

        if merged_titles:
            summary = (f"Merged {', '.join(merged_titles)} → "
                       f"#{keep_id} \"{keep_concept['title']}\" "
                       f"({g.get('reason', '')})")
            summaries.append(summary)

    return summaries
