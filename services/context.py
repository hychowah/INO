"""
Context & prompt building for the Learning Agent.
Constructs the dynamic context injected into every LLM call,
formats fetch results, and builds maintenance diagnostics.

Separated from tools.py (action handlers) and agent.py (CLI).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import db

logger = logging.getLogger("context")


def _read_file(path: Path) -> str:
    """Read file contents, return empty string if missing."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


# ============================================================================
# Lightweight Context (included in every LLM call)
# ============================================================================


def build_lightweight_context(mode: str = "command", is_new_session: bool = True) -> str:
    """Build the lightweight context string injected into LLM calls.
    Sections are conditional based on mode to minimize token usage.

    COMMAND/REPLY: all sections (topic map, due, stats, chat history)
    REVIEW-CHECK: due concepts only (skip topic map, stats, chat)
    MAINTENANCE: returns empty — maintenance uses its own context builder

    Args:
        is_new_session: When False AND session-based provider, skip chat history
            (provider already has full history in _sessions). On first turn
            (is_new=True), keep history for context bootstrapping.
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
    if stats["total_concepts"] == 0 and mode != "REVIEW-CHECK":
        topic_map = db.get_hierarchical_topic_map()
        if not topic_map:
            parts.append("Knowledge base is empty — waiting for first topic.\n")
            # Still include chat history for continuity
            _append_chat_history(parts, is_new_session=is_new_session)
            return "\n".join(parts)

    # --- REVIEW-CHECK: minimal context ---
    if mode == "REVIEW-CHECK":
        due = db.get_due_concepts(limit=5)
        parts.append("## Due for Review (top 5)")
        if due:
            for c in due:
                remark = c.get("latest_remark", "")
                remark_preview = f" | remark: {remark[:60]}" if remark else ""
                parts.append(
                    f"- [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                    f"interval {c['interval_days']}d, "
                    f"reviews: {c['review_count']}, topics: {c.get('topic_ids', [])}"
                    f"{remark_preview})"
                )
        else:
            parts.append("Nothing due right now.")
        parts.append("")
        return "\n".join(parts)

    # --- COMMAND/REPLY: full context ---
    # Topic map (root topics with inline subtopic names)
    topic_map = db.get_hierarchical_topic_map()
    parts.append(
        "## Knowledge Map (root topics — use `fetch` with `topic_id` to explore subtopics)"
    )
    if topic_map:
        for t in topic_map:
            sub = ""
            if t["subtopic_count"] > 0:
                children = db.get_topic_children(t["id"])
                child_names = ", ".join(c["title"] for c in children[:8])
                extra = f", +{len(children) - 8} more" if len(children) > 8 else ""
                sub = f", {t['subtopic_count']} subtopics ({child_names}{extra})"
            parts.append(
                f"- [topic:{t['id']}] {t['title']}: "
                f"{t['total_concepts']} concepts{sub}, "
                f"score {t['avg_mastery']}/100, {t['due_count']} due"
            )
    else:
        parts.append("No topics yet.")
    parts.append("")

    # Due concepts (top 5, with total count + top 2 relations each)
    due = db.get_due_concepts(limit=5)
    total_due = db.get_due_count()
    due_header = (
        f"## Due for Review (top 5 of {total_due})"
        if total_due > 5
        else "## Due for Review (top 5)"
    )
    parts.append(due_header)
    if due:
        for c in due:
            topic_ids = c.get("topic_ids", [])
            remark = c.get("latest_remark", "")
            remark_preview = f" | remark: {remark[:60]}" if remark else ""
            parts.append(
                f"- [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                f"interval {c['interval_days']}d, "
                f"reviews: {c['review_count']}, topics: {topic_ids}{remark_preview})"
            )
            # Show top 2 relations with score + remark snippet
            relations = db.get_relations(c["id"])
            for rel in relations[:2]:
                note_preview = f', "{rel["note"][:60]}"' if rel.get("note") else ""
                parts.append(
                    f"  ↳ {rel['relation_type']} #{rel['other_concept_id']} "
                    f"{rel['other_title']} (score {rel['other_mastery']}/100{note_preview})"
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

    # Auto-include active concept detail (eliminates 1 fetch round-trip)
    _append_active_concept_detail(parts)

    # Chat history
    _append_chat_history(parts, is_new_session=is_new_session)
    _append_active_quiz_context(parts)

    return "\n".join(parts)


def _append_active_concept_detail(parts: list) -> None:
    """If active_concept_id is set and not stale, include full concept detail
    with relations. Eliminates 1 fetch round-trip for the common case where
    the LLM needs this concept's data to proceed."""
    if _is_quiz_stale():
        return

    active_cid = db.get_session("active_concept_id")
    if not active_cid:
        return

    try:
        cid = int(active_cid)
    except (ValueError, TypeError):
        return

    detail = db.get_concept_detail(cid)
    if not detail:
        return

    parts.append(f"## Active Concept Detail: {detail['title']} (#{detail['id']})")
    parts.append(f"Description: {detail.get('description', 'N/A')}")
    parts.append(
        f"Score: {detail['mastery_level']}/100, "
        f"Interval: {detail['interval_days']}d, "
        f"Reviews: {detail['review_count']}"
    )
    parts.append(f"Topics: {[t['title'] for t in detail.get('topics', [])]}")

    if detail.get("remark_summary"):
        parts.append(f"Remark: {detail['remark_summary']}")

    if detail.get("recent_reviews"):
        parts.append("Recent reviews:")
        for r in detail["recent_reviews"][:3]:
            q = r.get("question_asked", "") or ""
            a = r.get("user_response", "") or ""
            parts.append(f"  - Q: {q[:150]}")
            parts.append(f"    A: {a[:150]}")
            parts.append(f"    Quality: {r['quality']}/5")

    rel_lines = _format_relations_snippet(cid, max_rels=3)
    if rel_lines:
        parts.append("Relations:")
        parts.extend(rel_lines)

    parts.append("")


def _is_quiz_stale() -> bool:
    """Check if the active quiz context is stale (past timeout).
    Returns True if stale or unparseable, False if fresh or no timestamp."""
    timeout_minutes = getattr(config, "QUIZ_STALENESS_TIMEOUT_MINUTES", 15)
    updated_at_str = db.get_session_updated_at("active_concept_id")
    if not updated_at_str:
        return False
    try:
        updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")
        elapsed = (datetime.now(timezone.utc).replace(tzinfo=None) - updated_at).total_seconds() / 60
        return elapsed > timeout_minutes
    except (ValueError, TypeError):
        logger.warning(
            f"Failed to parse quiz timestamp '{updated_at_str}', treating as stale."
        )
        return True


def _format_relations_snippet(concept_id: int, max_rels: int = 2) -> list[str]:
    """Return formatted relation lines for a concept (for inline context injection)."""
    lines = []
    relations = db.get_relations(concept_id)
    for rel in relations[:max_rels]:
        note_preview = f', "{rel["note"][:60]}"' if rel.get("note") else ""
        lines.append(
            f"  ↳ {rel['relation_type']} #{rel['other_concept_id']} "
            f"{rel['other_title']} (score {rel['other_mastery']}/100{note_preview})"
        )
    return lines


def _append_active_quiz_context(parts: list) -> None:
    """If there's an active quiz concept (single or multi), inject it so the LLM
    knows which concept_id(s) to use for assess.
    Auto-clears stale quiz context after QUIZ_STALENESS_TIMEOUT_MINUTES."""
    import json as _json

    # --- Staleness timeout safety net ---
    anchor_cid_pre = db.get_session("quiz_anchor_concept_id")
    stale = _is_quiz_stale()
    logger.debug(
        f"[quiz_anchor] Staleness check — anchor={anchor_cid_pre!r}, stale={stale}"
    )
    if stale:
        db.set_session("active_concept_id", None)
        db.set_session("active_concept_ids", None)
        db.set_session("quiz_anchor_concept_id", None)
        logger.debug("[quiz_anchor] CLEARED by staleness check")
        return

    # Check for multi-concept quiz first
    multi_ids_str = db.get_session("active_concept_ids")
    if multi_ids_str:
        try:
            concept_ids = _json.loads(multi_ids_str)
            if concept_ids and isinstance(concept_ids, list):
                concept_lines = []
                for cid in concept_ids:
                    c = db.get_concept(int(cid))
                    if c:
                        concept_lines.append(
                            f"- #{cid} — {c['title']} (score {c['mastery_level']}/100)"
                        )
                        concept_lines.extend(_format_relations_snippet(int(cid)))
                if concept_lines:
                    parts.append(
                        "## Active Multi-Concept Quiz\n"
                        "Concepts being quizzed together:\n"
                        + "\n".join(concept_lines)
                        + "\n\nUse `multi_assess` with individual scores per concept.\n"
                    )
                    return
        except (ValueError, TypeError):
            pass

    # Single-concept quiz — prefer quiz anchor (sacred) over active_concept_id
    # which may have been overwritten by fetch.  See DEVNOTES §16.
    anchor_cid = db.get_session("quiz_anchor_concept_id")
    active_cid = anchor_cid or db.get_session("active_concept_id")
    if active_cid:
        concept = db.get_concept(int(active_cid))
        if concept:
            rel_lines = _format_relations_snippet(int(active_cid))
            rel_section = "\n" + "\n".join(rel_lines) + "\n" if rel_lines else ""
            parts.append(
                f"## Active Quiz Context\n"
                f"Quizzed concept: **#{active_cid} — {concept['title']}** "
                f"(score {concept['mastery_level']}/100).{rel_section}"
                f"Use this concept_id for `assess` ONLY if the user's message actually "
                f"answers the quiz question. If they ask an unrelated question or change "
                f"topic, answer with REPLY: instead — do NOT assess. The quiz stays active "
                f"for when they return.\n"
            )


def _append_chat_history(parts: list, is_new_session: bool = True) -> None:
    """Append compressed chat history to context parts.
    Newest 4 messages: 600 chars, older 8: 150 chars (12 total).

    For session-based LLM providers (OpenAI-compat) on continuation turns
    (is_new_session=False), the provider already has full conversation
    history in _sessions — skip the section entirely to avoid duplication.
    On the first turn of a new session (is_new_session=True), include
    history since _sessions is empty and needs bootstrapping.
    """
    from services.llm import get_provider

    provider = get_provider()
    session_based = hasattr(provider, "_sessions")

    # Session-based provider on a continuation turn: skip entirely.
    # The provider's _sessions already has the full conversation.
    if session_based and not is_new_session:
        return

    limit = 12
    history = db.get_chat_history(limit=limit)

    parts.append("## Recent Conversation")
    if history:
        for i, msg in enumerate(history):
            role = "User" if msg["role"] == "user" else "Agent"
            content = msg["content"]
            if i >= len(history) - 4:
                # Newest 4 messages: 600 chars
                content = content[:600]
                if len(msg["content"]) > 600:
                    content += "..."
            else:
                # Older messages: 150 chars
                content = content[:150]
                if len(msg["content"]) > 150:
                    content += "..."
            parts.append(f"{role}: {content}")
    else:
        parts.append("No recent conversation.")
    parts.append("")


# ============================================================================
# Prompt Construction
# ============================================================================


def _preload_mentioned_concept(user_message: str) -> str:
    """If the user's message exactly matches a concept title (case-insensitive),
    pre-load its detail to eliminate a fetch round-trip.
    Returns formatted concept detail string, or empty string if no match.
    Only exact full-message matches — no substring or fuzzy matching."""
    text = user_message.strip()
    if not text or len(text) > 200:
        return ""

    concept = db.find_concept_by_title(text)
    if not concept:
        return ""

    # Topic relevance filter: if there's an active concept in session,
    # only pre-fetch if the matched concept shares at least one topic.
    active_cid = db.get_session("active_concept_id")
    if active_cid:
        try:
            active_detail = db.get_concept_detail(int(active_cid))
            if active_detail:
                active_topics = {t["id"] for t in active_detail.get("topics", [])}
                matched_topics = set(concept.get("topic_ids", []))
                if active_topics and matched_topics and not (active_topics & matched_topics):
                    return ""  # Different topic context; skip pre-fetch
        except (ValueError, TypeError):
            pass

    detail = db.get_concept_detail(concept["id"])
    if not detail:
        return ""

    parts = []
    parts.append(
        f"## Pre-loaded Concept (matched from message): {detail['title']} (#{detail['id']})"
    )
    parts.append(f"Description: {detail.get('description', 'N/A')}")
    parts.append(
        f"Score: {detail['mastery_level']}/100, "
        f"Interval: {detail['interval_days']}d, "
        f"Reviews: {detail['review_count']}"
    )
    parts.append(f"Topics: {[t['title'] for t in detail.get('topics', [])]}")

    if detail.get("remark_summary"):
        parts.append(f"Remark: {detail['remark_summary']}")

    rel_lines = _format_relations_snippet(detail["id"], max_rels=3)
    if rel_lines:
        parts.append("Relations:")
        parts.extend(rel_lines)

    parts.append("")
    return "\n".join(parts)


def build_prompt_context(
    user_message: str, mode: str = "command", is_new_session: bool = True
) -> str:
    """Build only the dynamic context (no AGENTS.md/preferences content).
    Used by the pipeline which tells kimi-cli to read AGENTS.md by file path.
    Note: user_message is NOT included here — the pipeline appends it separately
    to avoid duplication."""
    lightweight = build_lightweight_context(mode, is_new_session=is_new_session)

    # Pre-load concept if user message exactly matches a concept title
    preloaded = ""
    if mode.upper() not in ("MAINTENANCE", "REVIEW-CHECK"):
        preloaded = _preload_mentioned_concept(user_message)

    return f"""{lightweight}
{preloaded}## Mode
You are in {mode.upper()} mode.

## Your Response

Analyze the user's intent and respond in the required format."""


def build_quiz_generator_context(concept_id: int) -> str | None:
    """Build pre-loaded context for the quiz question generator (Prompt 1).

    Returns a structured text payload with concept detail + related concepts,
    or None if the concept is not found. No knowledge map, chat history, or
    stats — only what the reasoning model needs for question generation.
    """
    detail = db.get_concept_detail(concept_id)
    if not detail:
        return None

    parts = []

    # --- Primary concept ---
    parts.append(f"## Primary Concept: {detail['title']} (#{detail['id']})")
    parts.append(f"Description: {detail.get('description', 'N/A')}")
    parts.append(
        f"Score: {detail['mastery_level']}/100, "
        f"Interval: {detail['interval_days']}d, "
        f"Reviews: {detail['review_count']}"
    )
    parts.append(f"Topics: {[t['title'] for t in detail.get('topics', [])]}")

    if detail.get("remark_summary"):
        parts.append(f"\nRemark summary (updated {detail.get('remark_updated_at', 'N/A')}):")
        parts.append(f"  {detail['remark_summary']}")
    elif detail.get("remarks"):
        parts.append("\nRemarks (latest 3):")
        for r in detail["remarks"][:3]:
            parts.append(f"  - [{r['created_at']}] {r['content']}")

    if detail.get("recent_reviews"):
        parts.append("\nRecent reviews:")
        for r in detail["recent_reviews"]:
            q = r.get("question_asked", "") or ""
            a = r.get("user_response", "") or ""
            assess = r.get("llm_assessment", "") or ""
            parts.append(f"  - Q: {q[:200]}")
            parts.append(f"    A: {a[:200]}")
            parts.append(f"    Quality: {r['quality']}/5 — {assess[:200]}")

    # --- Related concepts (enriched with description + recent reviews) ---
    relations = db.get_relations(concept_id)
    if relations:
        parts.append("\n## Related Concepts")
        for rel in relations[:5]:
            other_detail = db.get_concept_detail(rel["other_concept_id"])
            parts.append(
                f"- [{rel['relation_type']}] #{rel['other_concept_id']} "
                f"{rel['other_title']} (score {rel['other_mastery']}/100)"
            )
            if rel.get("note"):
                parts.append(f"    Note: {rel['note'][:100]}")
            if other_detail:
                desc = other_detail.get("description", "")
                if desc:
                    parts.append(f"    Description: {desc[:300]}")
                if other_detail.get("remark_summary"):
                    parts.append(f"    Remark: {other_detail['remark_summary'][:200]}")
                if other_detail.get("recent_reviews"):
                    for r in other_detail["recent_reviews"][:2]:
                        q = r.get("question_asked", "") or ""
                        a = r.get("user_response", "") or ""
                        parts.append(f"    Q: {q[:100]}")
                        parts.append(f"    A: {a[:100]}")
                        parts.append(f"    Quality: {r['quality']}/5")

    parts.append("")
    return "\n".join(parts)


# ============================================================================
# Fetch Result Formatting
# ============================================================================


def format_fetch_result(data: Any) -> str:
    """Format fetch result data into a readable string for the LLM context."""
    if isinstance(data, dict) and "error" in data:
        return f"## Fetch Error\n{data['error']}\n"

    parts = ["## Fetched Data\n"]

    if isinstance(data, dict):
        # Concept detail
        if "concept_detail" in data:
            c = data["concept_detail"]
            parts.append(f"### Concept: {c['title']} (#{c['id']})")
            parts.append(f"Description: {c.get('description', 'N/A')}")
            parts.append(
                f"Score: {c['mastery_level']}/100, "
                f"Interval: {c['interval_days']}d, Reviews: {c['review_count']}"
            )
            parts.append(f"Next review: {c.get('next_review_at', 'N/A')}")
            parts.append(f"Topics: {[t['title'] for t in c.get('topics', [])]}")

            if c.get("remark_summary"):
                parts.append(f"\nRemark summary (updated {c.get('remark_updated_at', 'N/A')}):")
                parts.append(f"  {c['remark_summary']}")
            elif c.get("remarks"):
                # Fallback to raw remarks if summary not yet populated
                parts.append("\nRemarks (latest 3):")
                for r in c["remarks"][:3]:  # cap at 3 most recent
                    parts.append(f"  - [{r['created_at']}] {r['content']}")

            if c.get("recent_reviews"):
                parts.append("\nRecent reviews:")
                for r in c["recent_reviews"]:
                    q = r.get("question_asked", "") or ""
                    a = r.get("user_response", "") or ""
                    assess = r.get("llm_assessment", "") or ""
                    parts.append(f"  - Q: {q[:200]}")
                    parts.append(f"    A: {a[:200]}")
                    parts.append(f"    Quality: {r['quality']}/5 — {assess[:200]}")

            # Cross-concept relationships
            relations = db.get_relations(c["id"])
            if relations:
                parts.append("\nRelated Concepts:")
                for rel in relations:
                    parts.append(
                        f"  - [{rel['relation_type']}] "
                        f"[concept:{rel['other_concept_id']}] {rel['other_title']} "
                        f"(score {rel['other_mastery']}/100)"
                    )
            parts.append("")

        # Topic detail with concepts
        elif "topic" in data:
            t = data["topic"]
            parts.append(f"### Topic: {t['title']} (#{t['id']})")
            parts.append(f"Description: {t.get('description', 'N/A')}")

            if data.get("parent_topics"):
                parts.append(f"Parents: {[p['title'] for p in data['parent_topics']]}")
            if data.get("child_topics"):
                parts.append(f"Children: {[c['title'] for c in data['child_topics']]}")

            concepts = data.get("concepts", [])
            parts.append(f"\nConcepts ({len(concepts)}):")
            for c in concepts:
                remark = c.get("latest_remark", "")
                remark_str = f" | {remark[:50]}" if remark else ""
                parts.append(
                    f"  - [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                    f"next: {c.get('next_review_at', 'N/A')}{remark_str})"
                )
            parts.append("")

        # Search results
        elif "search_query" in data:
            parts.append(f'### Search: "{data["search_query"]}"')
            topics = data.get("matching_topics", [])
            concepts = data.get("matching_concepts", [])
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
        elif "due_concepts" in data:
            due = data["due_concepts"]
            parts.append(f"### Due Concepts ({len(due)})")
            for c in due:
                parts.append(
                    f"  - [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                    f"next: {c.get('next_review_at', 'N/A')}, topics: {c.get('topic_ids', [])})"
                )
            parts.append("")

        # Stats
        elif "stats" in data:
            s = data["stats"]
            parts.append("### Review Stats")
            parts.append(json.dumps(s, indent=2))
            parts.append("")

        # Concept cluster (multi-concept quiz context)
        elif "concept_cluster" in data:
            cluster = data["concept_cluster"]
            primary_id = data.get("primary_concept_id")
            parts.append(f"### Concept Cluster ({len(cluster)} concepts)")
            parts.append(f"Primary concept: #{primary_id}\n")

            for c in cluster:
                is_primary = c["id"] == primary_id
                label = " [PRIMARY]" if is_primary else ""
                sim = c.get("cluster_similarity")
                sim_str = f" (similarity: {sim:.2f})" if sim else ""
                parts.append(
                    f"#### {'➤ ' if is_primary else '  '}{c['title']} (#{c['id']}){label}{sim_str}"
                )
                parts.append(f"Description: {c.get('description', 'N/A')}")
                parts.append(
                    f"Score: {c['mastery_level']}/100, "
                    f"Interval: {c['interval_days']}d, Reviews: {c['review_count']}"
                )
                parts.append(f"Topics: {[t['title'] for t in c.get('topics', [])]}")

                if c.get("remark_summary"):
                    parts.append(f"Remark summary: {c['remark_summary'][:300]}")
                elif c.get("remarks"):
                    latest = c["remarks"][0] if c["remarks"] else None
                    if latest:
                        parts.append(f"Latest remark: {latest['content'][:200]}")

                if c.get("recent_reviews"):
                    parts.append("Recent reviews:")
                    for r in c["recent_reviews"][:2]:
                        q = r.get("question_asked", "") or ""
                        parts.append(f"  - Q: {q[:150]} | Quality: {r['quality']}/5")
                parts.append("")

            parts.append(
                "Use `multi_quiz` with all concept_ids above to ask a synthesis question "
                "that tests understanding across these related concepts.\n"
            )

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
    parts.append(
        f"Root topics: {len(topic_map)} | Concepts: {stats['total_concepts']} | "
        f"Due now: {stats['due_now']} | Reviews (7d): {stats['reviews_last_7d']} | "
        f"Avg score: {stats['avg_mastery']}/100\n"
    )

    # Hierarchical topic map
    parts.append("### Topic Map (root topics — fetch to drill into subtrees)")
    if topic_map:
        for t in topic_map:
            sub = f", {t['subtopic_count']} subtopics" if t["subtopic_count"] > 0 else ""
            parts.append(
                f"- [topic:{t['id']}] {t['title']}: "
                f"{t['total_concepts']} concepts{sub}, score {t['avg_mastery']}/100"
            )
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

    if diag["untagged_concepts"]:
        n = len(diag["untagged_concepts"])
        issue_count += n
        parts.append(f"### ⚠️ Untagged Concepts ({_cap_label(n)})")
        for c in diag["untagged_concepts"]:
            parts.append(
                f"- [concept:{c['id']}] {c['title']} (score {c['mastery_level']}/100, "
                f"reviews: {c['review_count']}, created: {c['created_at']})"
            )
        parts.append("")

    if diag["empty_topics"]:
        n = len(diag["empty_topics"])
        issue_count += n
        parts.append(f"### ⚠️ Empty Topics ({_cap_label(n)})")
        for t in diag["empty_topics"]:
            parts.append(f"- [topic:{t['id']}] {t['title']} (created: {t['created_at']})")
        parts.append("")

    if diag["oversized_topics"]:
        n = len(diag["oversized_topics"])
        issue_count += n
        parts.append(f"### ⚠️ Oversized Topics ({_cap_label(n)})")
        for t in diag["oversized_topics"]:
            parts.append(
                f"- [topic:{t['id']}] {t['title']}: {t['concept_count']} concepts"
                " — consider splitting"
            )
        parts.append("")

    if diag["stale_concepts"]:
        n = len(diag["stale_concepts"])
        issue_count += n
        parts.append(f"### ⚠️ Stale Concepts ({_cap_label(n)})")
        parts.append("(Created >14 days ago, never reviewed)")
        for c in diag["stale_concepts"]:
            parts.append(f"- [concept:{c['id']}] {c['title']} (created: {c['created_at']})")
        parts.append("")

    if diag["struggling_concepts"]:
        n = len(diag["struggling_concepts"])
        issue_count += n
        parts.append(f"### ⚠️ Struggling Concepts ({_cap_label(n)})")
        parts.append(
            "(5+ reviews but score ≤ 25 — DO NOT adjust scores. "
            "Suggest remarks or concept splitting only.)"
        )
        for c in diag["struggling_concepts"]:
            parts.append(
                f"- [concept:{c['id']}] {c['title']} ({c['review_count']} reviews, still building)"
            )
        parts.append("")

    if diag["over_tagged_concepts"]:
        n = len(diag["over_tagged_concepts"])
        issue_count += n
        parts.append(f"### ⚠️ Over-tagged Concepts ({_cap_label(n)})")
        for c in diag["over_tagged_concepts"]:
            parts.append(f"- [concept:{c['id']}] {c['title']}: in {c['topic_count']} topics")
        parts.append("")

    if diag.get("relationship_candidates"):
        n = len(diag["relationship_candidates"])
        parts.append(f"### 🔗 Relationship Candidates ({_cap_label(n)})")
        parts.append(
            "(Concepts that share keywords but have no relation"
            " — review for pedagogical connections)"
        )
        for pair in diag["relationship_candidates"]:
            a, b = pair["concept_a"], pair["concept_b"]
            parts.append(
                f"- [concept:{a['id']}] {a['title']} ↔ [concept:{b['id']}] {b['title']}"
                f" (similarity: {pair['similarity']})"
            )
        parts.append("")

    if diag.get("cluttered_root_topics"):
        n = len(diag["cluttered_root_topics"])
        issue_count += n
        parts.append(f"### ⚠️ Cluttered Root Topics ({_cap_label(n)})")
        parts.append("(Root topics with >10 concepts and no subtopics — suggest splitting)")
        for t in diag["cluttered_root_topics"]:
            parts.append(f"- [topic:{t['id']}] {t['title']}: {t['concept_count']} concepts")
        parts.append("")

    # Note: potential_duplicates are handled by the dedicated dedup sub-agent
    # (pipeline.handle_dedup_check), not the maintenance agent.

    if issue_count == 0:
        parts.append("### ✅ No issues found — knowledge base is healthy!\n")

    parts.append(f"**Total issues: {issue_count}**")

    return "\n".join(parts)


# ============================================================================
# Taxonomy Context
# ============================================================================


def build_taxonomy_context() -> str:
    """Build context for the taxonomy reorganization agent.

    Provides the full topic tree with indented hierarchy, root-topic
    candidates for grouping, and a suppressed-renames block so the LLM
    won't re-propose renames the user already rejected.
    """
    parts = []
    now = datetime.now()
    parts.append(f"## Taxonomy Reorganization — {now.strftime('%Y-%m-%d %H:%M:%S')}\n")

    topic_map = db.get_topic_map()  # flat list: {id, title, concept_count, parent_ids, child_ids}
    stats = db.get_review_stats()

    # Overview
    root_topics = [t for t in topic_map if not t["parent_ids"]]
    parts.append("### Overview")
    parts.append(
        f"Total topics: {len(topic_map)} | Root topics: {len(root_topics)} | "
        f"Concepts: {stats['total_concepts']} | Avg score: {stats['avg_mastery']}/100\n"
    )

    # Build children lookup for DFS
    children: dict[int, list[int]] = {}
    topic_by_id: dict[int, dict] = {}
    for t in topic_map:
        topic_by_id[t["id"]] = t
        for cid in t.get("child_ids", []):
            children.setdefault(t["id"], []).append(cid)

    # Indented topic tree via iterative DFS
    parts.append("### Full Topic Tree")
    parts.append(
        "(indent = hierarchy depth; [topic:ID] = reference for actions; "
        "N concepts = concept count directly tagged)\n"
    )

    def _render_tree(node_id: int, depth: int, visited: set) -> list[str]:
        if node_id in visited:
            return []
        visited.add(node_id)
        t = topic_by_id.get(node_id)
        if not t:
            return []
        indent = "  " * depth
        lines = [
            f"{indent}[topic:{t['id']}] {t['title']} ({t['concept_count']} concepts)"
        ]
        for child_id in sorted(children.get(node_id, [])):
            lines.extend(_render_tree(child_id, depth + 1, visited))
        return lines

    visited: set = set()
    root_ids = sorted(t["id"] for t in root_topics)
    tree_lines = []
    for rid in root_ids:
        tree_lines.extend(_render_tree(rid, 0, visited))

    # Orphaned topics (no parent and not in a tree, e.g. cycles broken) — append flat
    for t in topic_map:
        if t["id"] not in visited:
            tree_lines.append(
                f"⚠️ [topic:{t['id']}] {t['title']} ({t['concept_count']} concepts) [orphaned]"
            )

    if tree_lines:
        parts.extend(tree_lines)
    else:
        parts.append("No topics yet.")
    parts.append("")

    # Root topics as grouping candidates
    parts.append("### Root Topics (candidates for new parent grouping)")
    parts.append(
        "(If 3+ root topics share a clear theme, propose a new parent topic "
        "and `link_topics` each under it.)\n"
    )
    for t in root_topics:
        parts.append(
            f"- [topic:{t['id']}] {t['title']}: {t['concept_count']} concepts"
        )
    parts.append("")

    # Suppressed renames
    try:
        rejected = db.get_rejected_renames(days=90)
    except Exception:
        rejected = []

    if rejected:
        parts.append("### ⛔ Suppressed Renames (do NOT propose these again)")
        parts.append(
            "(These were previously proposed and rejected by the user. "
            "Skip them entirely — do not mention, do not re-propose.)\n"
        )
        for r in rejected:
            target_ref = f"[topic:{r['target_id']}]" if r["action"] == "update_topic" else \
                         f"[concept:{r['target_id']}]"
            title_note = f' → "{r["proposed_title"]}"' if r["proposed_title"] else ""
            parts.append(
                f"- {target_ref}{title_note} — rejected on {r['rejected_at'][:10]}"
            )
        parts.append("")

    return "\n".join(parts)
