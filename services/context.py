"""
Context & prompt building for the Learning Agent.
Constructs the dynamic context injected into every LLM call,
formats fetch results, and builds maintenance diagnostics.

Separated from tools.py (action handlers) and agent.py (CLI).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import db

AGENTS_MD_PATH = Path(__file__).parent.parent / "AGENTS.md"
PREFERENCES_MD_PATH = Path(__file__).parent.parent / "preferences.md"


def _read_file(path: Path) -> str:
    """Read file contents, return empty string if missing."""
    if path.exists():
        return path.read_text(encoding='utf-8')
    return ""


# ============================================================================
# Lightweight Context (included in every LLM call)
# ============================================================================

def build_lightweight_context(mode: str = "command") -> str:
    """Build the lightweight context string injected into LLM calls.
    Sections are conditional based on mode to minimize token usage.

    COMMAND/REPLY: all sections (topic map, due, stats, chat history)
    REVIEW-CHECK: due concepts only (skip topic map, stats, chat)
    MAINTENANCE: returns empty — maintenance uses its own context builder
    """
    mode = mode.upper()

    # Maintenance builds its own context — no lightweight needed
    if mode == "MAINTENANCE":
        return ""

    parts = []
    now = datetime.now()

    # Current time (always included)
    parts.append(f"## Current Time\n{now.strftime('%Y-%m-%d %H:%M:%S')} ({now.strftime('%A')})\n")

    # Quick check: is the DB empty? If so, short-circuit.
    stats = db.get_review_stats()
    if stats['total_concepts'] == 0 and mode != "REVIEW-CHECK":
        topic_map = db.get_hierarchical_topic_map()
        if not topic_map:
            parts.append("Knowledge base is empty — waiting for first topic.\n")
            # Still include chat history for continuity
            _append_chat_history(parts)
            return "\n".join(parts)

    # --- REVIEW-CHECK: minimal context ---
    if mode == "REVIEW-CHECK":
        due = db.get_due_concepts(limit=5)
        parts.append("## Due for Review (top 5)")
        if due:
            for c in due:
                remark = c.get('latest_remark', '')
                remark_preview = f" | remark: {remark[:60]}" if remark else ""
                parts.append(
                    f"- [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                    f"interval {c['interval_days']}d, "
                    f"reviews: {c['review_count']}, topics: {c.get('topic_ids', [])}{remark_preview})"
                )
        else:
            parts.append("Nothing due right now.")
        parts.append("")
        return "\n".join(parts)

    # --- COMMAND/REPLY: full context ---
    # Topic map (root topics only)
    topic_map = db.get_hierarchical_topic_map()
    parts.append("## Knowledge Map (root topics — use `fetch` with `topic_id` to explore subtopics)")
    if topic_map:
        for t in topic_map:
            sub = f", {t['subtopic_count']} subtopics" if t['subtopic_count'] > 0 else ""
            parts.append(
                f"- [topic:{t['id']}] {t['title']}: "
                f"{t['total_concepts']} concepts{sub}, "
                f"score {t['avg_mastery']}/100, {t['due_count']} due"
            )
    else:
        parts.append("No topics yet.")
    parts.append("")

    # Due concepts (top 5)
    due = db.get_due_concepts(limit=5)
    parts.append("## Due for Review (top 5)")
    if due:
        for c in due:
            topic_ids = c.get('topic_ids', [])
            remark = c.get('latest_remark', '')
            remark_preview = f" | remark: {remark[:60]}" if remark else ""
            parts.append(
                f"- [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                f"interval {c['interval_days']}d, "
                f"reviews: {c['review_count']}, topics: {topic_ids}{remark_preview})"
            )
    else:
        parts.append("Nothing due right now.")
    parts.append("")

    # Review stats
    parts.append(
        f"## Stats\n"
        f"Total concepts: {stats['total_concepts']} | Due now: {stats['due_now']} | "
        f"Reviews (7d): {stats['reviews_last_7d']} | Avg score: {stats['avg_mastery']}/100\n"
    )

    # Chat history
    _append_chat_history(parts)
    _append_active_quiz_context(parts)

    return "\n".join(parts)


def _append_active_quiz_context(parts: list) -> None:
    """If there's an active quiz concept, inject it so the LLM knows which
    concept_id to use for assess — survives chat history truncation."""
    active_cid = db.get_session('active_concept_id')
    if active_cid:
        concept = db.get_concept(int(active_cid))
        if concept:
            parts.append(
                f"## Active Quiz Context\n"
                f"Last fetched/quizzed concept: **#{active_cid} — {concept['title']}**. "
                f"Use this concept_id for `assess` actions unless the conversation "
                f"has clearly moved to a different topic.\n"
            )


def _append_chat_history(parts: list) -> None:
    """Append compressed chat history to context parts.
    Newest 4 messages: 600 chars, older 8: 150 chars (12 total)."""
    history = db.get_chat_history(limit=12)
    parts.append("## Recent Conversation")
    if history:
        for i, msg in enumerate(history):
            role = "User" if msg['role'] == 'user' else "Agent"
            content = msg['content']
            if i >= len(history) - 4:
                # Newest 4 messages: 600 chars
                content = content[:600]
                if len(msg['content']) > 600:
                    content += "..."
            else:
                # Older messages: 150 chars
                content = content[:150]
                if len(msg['content']) > 150:
                    content += "..."
            parts.append(f"{role}: {content}")
    else:
        parts.append("No recent conversation.")
    parts.append("")


# ============================================================================
# Prompt Construction
# ============================================================================

def build_prompt_context(user_message: str, mode: str = "command") -> str:
    """Build only the dynamic context (no AGENTS.md/preferences content).
    Used by the pipeline which tells kimi-cli to read AGENTS.md by file path.
    Note: user_message is NOT included here — the pipeline appends it separately
    to avoid duplication."""
    lightweight = build_lightweight_context(mode)

    return f"""{lightweight}
## Mode
You are in {mode.upper()} mode.

## Your Response

Analyze the user's intent and respond in the required format."""


def build_full_prompt(user_message: str, mode: str = "command") -> str:
    """Build a complete prompt including AGENTS.md + preferences + context.
    Used for standalone execution (not via Discord bot)."""
    agents_md = _read_file(AGENTS_MD_PATH)
    preferences_md = _read_file(PREFERENCES_MD_PATH)
    lightweight = build_lightweight_context(mode)

    return f"""{agents_md}

## User Preferences

{preferences_md}

{lightweight}

## Mode
You are in {mode.upper()} mode.

## User Message

{user_message}

## Your Response

Analyze the user's intent and respond in the required format."""


# ============================================================================
# Fetch Result Formatting
# ============================================================================

def format_fetch_result(data: Any) -> str:
    """Format fetch result data into a readable string for the LLM context."""
    if isinstance(data, dict) and 'error' in data:
        return f"## Fetch Error\n{data['error']}\n"

    parts = ["## Fetched Data\n"]

    if isinstance(data, dict):
        # Concept detail
        if 'concept_detail' in data:
            c = data['concept_detail']
            parts.append(f"### Concept: {c['title']} (#{c['id']})")
            parts.append(f"Description: {c.get('description', 'N/A')}")
            parts.append(f"Score: {c['mastery_level']}/100, "
                         f"Interval: {c['interval_days']}d, Reviews: {c['review_count']}")
            parts.append(f"Next review: {c.get('next_review_at', 'N/A')}")
            parts.append(f"Topics: {[t['title'] for t in c.get('topics', [])]}")

            if c.get('remarks'):
                parts.append("\nRemarks (latest 3):")
                for r in c['remarks'][:3]:  # cap at 3 most recent
                    parts.append(f"  - [{r['created_at']}] {r['content']}")

            if c.get('recent_reviews'):
                parts.append("\nRecent reviews:")
                for r in c['recent_reviews']:
                    q = r.get('question_asked', '') or ''
                    a = r.get('user_response', '') or ''
                    assess = r.get('llm_assessment', '') or ''
                    parts.append(f"  - Q: {q[:200]}")
                    parts.append(f"    A: {a[:200]}")
                    parts.append(f"    Quality: {r['quality']}/5 — {assess[:200]}")
            parts.append("")

        # Topic detail with concepts
        elif 'topic' in data:
            t = data['topic']
            parts.append(f"### Topic: {t['title']} (#{t['id']})")
            parts.append(f"Description: {t.get('description', 'N/A')}")

            if data.get('parent_topics'):
                parts.append(f"Parents: {[p['title'] for p in data['parent_topics']]}")
            if data.get('child_topics'):
                parts.append(f"Children: {[c['title'] for c in data['child_topics']]}")

            concepts = data.get('concepts', [])
            parts.append(f"\nConcepts ({len(concepts)}):")
            for c in concepts:
                remark = c.get('latest_remark', '')
                remark_str = f" | {remark[:50]}" if remark else ""
                parts.append(
                    f"  - [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                    f"next: {c.get('next_review_at', 'N/A')}{remark_str})"
                )
            parts.append("")

        # Search results
        elif 'search_query' in data:
            parts.append(f"### Search: \"{data['search_query']}\"")
            topics = data.get('matching_topics', [])
            concepts = data.get('matching_concepts', [])
            if topics:
                parts.append(f"Topics ({len(topics)}):")
                for t in topics:
                    parts.append(f"  - [topic:{t['id']}] {t['title']}")
            if concepts:
                parts.append(f"Concepts ({len(concepts)}):")
                for c in concepts:
                    parts.append(
                        f"  - [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                        f"topics: {c.get('topic_ids', [])})"
                    )
            if not topics and not concepts:
                parts.append("No matches found.")
            parts.append("")

        # Due concepts
        elif 'due_concepts' in data:
            due = data['due_concepts']
            parts.append(f"### Due Concepts ({len(due)})")
            for c in due:
                parts.append(
                    f"  - [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                    f"next: {c.get('next_review_at', 'N/A')}, topics: {c.get('topic_ids', [])})"
                )
            parts.append("")

        # Stats
        elif 'stats' in data:
            s = data['stats']
            parts.append("### Review Stats")
            parts.append(json.dumps(s, indent=2))
            parts.append("")

        else:
            parts.append(json.dumps(data, indent=2, default=str))
    else:
        parts.append(str(data))

    return "\n".join(parts)


# ============================================================================
# Maintenance Context
# ============================================================================

def build_maintenance_context() -> str:
    """Build diagnostic context for the maintenance agent.
    Surfaces DB health issues so the LLM can decide what to fix."""
    parts = []
    now = datetime.now()
    parts.append(f"## Maintenance Check — {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

    diag = db.get_maintenance_diagnostics()
    stats = db.get_review_stats()
    topic_map = db.get_hierarchical_topic_map()

    # Overall stats
    parts.append("### Overview")
    parts.append(f"Root topics: {len(topic_map)} | Concepts: {stats['total_concepts']} | "
                 f"Due now: {stats['due_now']} | Reviews (7d): {stats['reviews_last_7d']} | "
                 f"Avg score: {stats['avg_mastery']}/100\n")

    # Hierarchical topic map
    parts.append("### Topic Map (root topics — fetch to drill into subtrees)")
    if topic_map:
        for t in topic_map:
            sub = f", {t['subtopic_count']} subtopics" if t['subtopic_count'] > 0 else ""
            parts.append(f"- [topic:{t['id']}] {t['title']}: "
                         f"{t['total_concepts']} concepts{sub}, score {t['avg_mastery']}/100")
    else:
        parts.append("No topics yet.")
    parts.append("")

    # Flat list for similarity reasoning
    all_topics = db.get_all_topics()
    if len(all_topics) > len(topic_map):
        parts.append("### All Topic Titles (scan for similar/mergeable pairs)")
        for t in all_topics:
            parts.append(f"- [topic:{t['id']}] {t['title']}")
        parts.append("")

    issue_count = 0
    CAP = 20

    def _cap_label(n):
        return f"{n}+ (capped)" if n >= CAP else str(n)

    if diag['untagged_concepts']:
        n = len(diag['untagged_concepts'])
        issue_count += n
        parts.append(f"### ⚠️ Untagged Concepts ({_cap_label(n)})")
        for c in diag['untagged_concepts']:
            parts.append(f"- [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                         f"reviews: {c['review_count']}, created: {c['created_at']})")
        parts.append("")

    if diag['empty_topics']:
        n = len(diag['empty_topics'])
        issue_count += n
        parts.append(f"### ⚠️ Empty Topics ({_cap_label(n)})")
        for t in diag['empty_topics']:
            parts.append(f"- [topic:{t['id']}] {t['title']} (created: {t['created_at']})")
        parts.append("")

    if diag['oversized_topics']:
        n = len(diag['oversized_topics'])
        issue_count += n
        parts.append(f"### ⚠️ Oversized Topics ({_cap_label(n)})")
        for t in diag['oversized_topics']:
            parts.append(f"- [topic:{t['id']}] {t['title']}: {t['concept_count']} concepts — consider splitting")
        parts.append("")

    if diag['stale_concepts']:
        n = len(diag['stale_concepts'])
        issue_count += n
        parts.append(f"### ⚠️ Stale Concepts ({_cap_label(n)})")
        parts.append("(Created >14 days ago, never reviewed)")
        for c in diag['stale_concepts']:
            parts.append(f"- [concept:{c['id']}] {c['title']} (created: {c['created_at']})")
        parts.append("")

    if diag['struggling_concepts']:
        n = len(diag['struggling_concepts'])
        issue_count += n
        parts.append(f"### ⚠️ Struggling Concepts ({_cap_label(n)})")
        parts.append("(5+ reviews but score ≤ 25 — DO NOT adjust scores. "
                     "Suggest remarks or concept splitting only.)")
        for c in diag['struggling_concepts']:
            parts.append(f"- [concept:{c['id']}] {c['title']} "
                         f"({c['review_count']} reviews, still building)")
        parts.append("")

    if diag['over_tagged_concepts']:
        n = len(diag['over_tagged_concepts'])
        issue_count += n
        parts.append(f"### ⚠️ Over-tagged Concepts ({_cap_label(n)})")
        for c in diag['over_tagged_concepts']:
            parts.append(f"- [concept:{c['id']}] {c['title']}: in {c['topic_count']} topics")
        parts.append("")

    # Note: potential_duplicates are handled by the dedicated dedup sub-agent
    # (pipeline.handle_dedup_check), not the maintenance agent.

    if issue_count == 0:
        parts.append("### ✅ No issues found — knowledge base is healthy!\n")

    parts.append(f"**Total issues: {issue_count}**")

    return "\n".join(parts)
