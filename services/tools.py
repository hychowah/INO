"""
Action executor for Learning Agent.
Maps action verbs from LLM JSON responses to db operations.
"""

import contextvars
import logging
from typing import Any, Dict, List, Optional, Tuple

import db

logger = logging.getLogger("tools")

# preferences path: use config.PREFERENCES_MD if needed

# ============================================================================
# Action source tracking via contextvars (task-scoped, no signature threading)
# ============================================================================

_action_source: contextvars.ContextVar[str] = contextvars.ContextVar(
    "action_source", default="discord"
)


def set_action_source(source: str) -> None:
    """Set the action source for the current context (discord/scheduler/maintenance/api/cli)."""
    _action_source.set(source)


def get_action_source() -> str:
    """Get the current action source."""
    return _action_source.get()


# Actions that are read-only / no-ops — don't log these
_SKIP_LOG_ACTIONS = frozenset({"fetch", "list_topics", "none", "reply"})


# ============================================================================
# Action Executor
# ============================================================================


def execute_action(action: str, params: Dict[str, Any]) -> Tuple[str, Any]:
    """Execute a parsed LLM action against the database.

    Returns (message_type, result) where message_type is one of:
      'reply'  — text to show the user
      'fetch'  — data to feed back to the LLM (fetch loop)
      'error'  — something went wrong
    """
    action = action.lower().strip()
    handler = ACTION_HANDLERS.get(action)
    if not handler:
        return ("error", f"Unknown action: {action}")

    try:
        msg_type, result = handler(params)
    except Exception as e:
        msg_type, result = ("error", f"Error executing '{action}': {e}")

    # Log mutating actions to the audit trail
    if action not in _SKIP_LOG_ACTIONS:
        try:
            db.log_action(
                action=action,
                params=params,
                result_type=msg_type,
                result=str(result)[:500] if result else "",
                source=_action_source.get(),
            )
        except Exception:
            logger.warning(f"Failed to log action '{action}'", exc_info=True)

    return (msg_type, result)


# ============================================================================
# Fetch Handlers (return data for LLM, not user-visible)
# ============================================================================


def _handle_fetch(params: Dict) -> Tuple[str, Any]:
    """Fetch data from DB for the LLM's context enrichment loop."""
    # Cluster fetch must be checked before plain concept_id fetch
    if params.get("cluster") and "concept_id" in params:
        return _handle_fetch_cluster(params)

    if "concept_id" in params:
        detail = db.get_concept_detail(int(params["concept_id"]))
        if not detail:
            return ("fetch", {"error": f"Concept #{params['concept_id']} not found"})
        return ("fetch", {"concept_detail": detail})

    if "topic_id" in params:
        tid = int(params["topic_id"])
        topic = db.get_topic(tid)
        if not topic:
            return ("fetch", {"error": f"Topic #{tid} not found"})
        concepts = db.get_concepts_for_topic(tid)
        children = db.get_topic_children(tid)
        parents = db.get_topic_parents(tid)
        return (
            "fetch",
            {
                "topic": topic,
                "concepts": concepts,
                "child_topics": children,
                "parent_topics": parents,
            },
        )

    if "search" in params:
        query = params["search"]
        concepts = db.search_concepts(query, limit=params.get("limit", 20))
        topics = db.search_topics(query, limit=params.get("limit", 10))
        return (
            "fetch",
            {
                "search_query": query,
                "matching_concepts": concepts,
                "matching_topics": topics,
            },
        )

    if params.get("due"):
        limit = int(params.get("limit", 10))
        due = db.get_due_concepts(limit=limit)
        if not due:
            # Nothing overdue — fall back to the nearest upcoming concept
            next_concept = db.get_next_review_concept()
            if next_concept:
                due = [next_concept]
        return ("fetch", {"due_concepts": due})

    if params.get("stats"):
        stats = db.get_review_stats()
        return ("fetch", {"stats": stats})

    return ("error", "fetch requires one of: concept_id, topic_id, search, due, stats, cluster")


# ============================================================================
# Topic Handlers
# ============================================================================


def _handle_add_topic(params: Dict) -> Tuple[str, Any]:
    parent_ids = params.get("parent_ids", [])
    if isinstance(parent_ids, int):
        parent_ids = [parent_ids]

    topic_id = db.add_topic(
        title=params["title"],
        description=params.get("description"),
        parent_ids=parent_ids or None,
    )
    # Stash for SuggestTopicConfirmView to retrieve after creation
    db.set_session("last_added_topic_id", str(topic_id))
    return ("reply", f"Created topic **{params['title']}** (#{topic_id})")


def _handle_update_topic(params: Dict) -> Tuple[str, Any]:
    tid = params.get("topic_id")
    if not tid:
        return ("error", "update_topic requires topic_id")

    updated = db.update_topic(
        int(tid), **{k: v for k, v in params.items() if k in ("title", "description")}
    )
    if updated:
        return ("reply", f"Updated topic #{tid}")
    return ("error", f"Topic #{tid} not found")


def _handle_delete_topic(params: Dict) -> Tuple[str, Any]:
    tid = params.get("topic_id")
    if not tid:
        return ("error", "delete_topic requires topic_id")

    topic = db.get_topic(int(tid))
    if not topic:
        return ("error", f"Topic #{tid} not found")

    # Guard: refuse to delete topics that still have concepts or children
    concepts = db.get_concepts_for_topic(int(tid))
    if concepts:
        return (
            "error",
            f"Cannot delete topic #{tid} '{topic['title']}': "
            f"still has {len(concepts)} concept(s). Unlink or move them first.",
        )
    children = db.get_topic_children(int(tid))
    if children:
        return (
            "error",
            f"Cannot delete topic #{tid} '{topic['title']}': "
            f"still has {len(children)} child topic(s). Unlink them first.",
        )

    db.delete_topic(int(tid))
    return ("reply", f"Deleted topic **{topic['title']}** (#{tid})")


def _handle_link_topics(params: Dict) -> Tuple[str, Any]:
    parent_id = params.get("parent_id")
    child_id = params.get("child_id")
    if not parent_id or not child_id:
        return ("error", "link_topics requires parent_id and child_id")

    ok = db.link_topics(int(parent_id), int(child_id))
    if ok:
        return ("reply", f"Linked topic #{parent_id} → #{child_id}")
    return ("error", "Could not link topics (same ID, already linked, or would create cycle)")


def _handle_unlink_topics(params: Dict) -> Tuple[str, Any]:
    parent_id = params.get("parent_id")
    child_id = params.get("child_id")
    if not parent_id or not child_id:
        return ("error", "unlink_topics requires parent_id and child_id")

    ok = db.unlink_topics(int(parent_id), int(child_id))
    if ok:
        return ("reply", f"Unlinked topic #{child_id} from parent #{parent_id}")
    return ("error", f"No parent→child link found between #{parent_id} and #{child_id}")


def _handle_list_topics(params: Dict) -> Tuple[str, Any]:
    topic_map = db.get_topic_map()
    if not topic_map:
        return ("reply", "No topics yet. Ask me a question or tell me what you want to learn!")

    lines = ["**Your Knowledge Map:**\n"]
    # Group: root topics (no parents) first, then indented children
    roots = [t for t in topic_map if not t["parent_ids"]]
    children_map = {}
    for t in topic_map:
        for pid in t["parent_ids"]:
            children_map.setdefault(pid, []).append(t)

    def _format_topic(t, indent=0):
        prefix = "  " * indent + ("└ " if indent > 0 else "• ")
        mastery_bar = _mastery_bar(t["avg_mastery"])
        due_str = f", **{t['due_count']} due**" if t["due_count"] > 0 else ""
        lines.append(
            f"{prefix}**{t['title']}** — {t['concept_count']} concepts, "
            f"mastery {mastery_bar}{due_str}"
        )
        for child in children_map.get(t["id"], []):
            _format_topic(child, indent + 1)

    for root in roots:
        _format_topic(root)

    # Orphan topics (have parents but parent not root — shouldn't happen in normal DAG,
    # but list them to avoid hiding anything)
    listed_ids = set()

    def _collect_ids(t):
        listed_ids.add(t["id"])
        for child in children_map.get(t["id"], []):
            _collect_ids(child)

    for root in roots:
        _collect_ids(root)

    orphans = [t for t in topic_map if t["id"] not in listed_ids]
    for t in orphans:
        _format_topic(t)

    stats = db.get_review_stats()
    lines.append(
        f"\n📊 Total: {stats['total_concepts']} concepts, "
        f"{stats['due_now']} due, "
        f"{stats['reviews_last_7d']} reviews this week"
    )

    return ("reply", "\n".join(lines))


def _mastery_bar(avg: float) -> str:
    """Simple text-based mastery indicator."""
    if avg is None or avg == 0:
        return "⬜⬜⬜⬜⬜ 0/5"
    filled = round(avg)
    return "🟩" * filled + "⬜" * (5 - filled) + f" {avg}/5"


# ============================================================================
# Concept Handlers
# ============================================================================


def _resolve_topic_ids(params: Dict) -> Tuple[List[int], List[Tuple[int, str]]]:
    """Resolve topic_ids and topic_titles into a flat list of topic IDs.
    Returns (topic_ids, created_topics) where created_topics is [(id, title), ...].

    When auto-creating a topic from topic_titles, uses semantic search to
    find a likely parent topic and sets parent_ids automatically.
    """
    topic_ids = params.get("topic_ids", [])
    if isinstance(topic_ids, int):
        topic_ids = [topic_ids]
    else:
        topic_ids = list(topic_ids)  # copy to avoid mutating params

    topic_titles = params.get("topic_titles", [])
    if isinstance(topic_titles, str):
        topic_titles = [topic_titles]
    if params.get("topic_title"):
        topic_titles.append(params["topic_title"])

    created_topics = []
    for title in topic_titles:
        # Deterministic exact-match first — avoids vector search edge cases
        exact = db.find_topic_by_title(title)
        if exact:
            topic_ids.append(exact["id"])
            continue
        matches = db.search_topics(title, limit=1)
        if matches and matches[0]["title"].lower() == title.lower():
            topic_ids.append(matches[0]["id"])
        else:
            # Auto-detect parent via semantic similarity before creation
            parent_ids = _find_candidate_parents(title)
            new_id = db.add_topic(title=title, parent_ids=parent_ids or None)
            topic_ids.append(new_id)
            created_topics.append((new_id, title))
            if parent_ids:
                parent_names = []
                for pid in parent_ids:
                    pt = db.get_topic(pid)
                    if pt:
                        parent_names.append(pt["title"])
                logger.info(f"[resolve_topic_ids] Auto-parented '{title}' under {parent_names}")

    return topic_ids, created_topics


def _find_candidate_parents(title: str, score_threshold: float = 0.50, limit: int = 3) -> List[int]:
    """Use semantic search to find existing topics that could be parents
    of a new topic with the given title.

    Returns a list of parent topic IDs (usually 0 or 1). Only returns topics
    whose title is a broader/shorter term than the new title — avoids
    suggesting peers or children as parents.
    """
    try:
        candidates = db.search_similar_topics(title, limit=limit, score_threshold=score_threshold)
    except Exception:
        # Vector store unavailable — no auto-parenting, not fatal
        return []

    parent_ids = []
    title_lower = title.lower()
    for c in candidates:
        c_title_lower = c["title"].lower()
        # Skip exact match (same topic being re-found)
        if c_title_lower == title_lower:
            continue
        # Heuristic: the candidate is a plausible parent if its title appears
        # as a substring of the new title (e.g. "Python" in "Python AST").
        # For high-similarity non-substring matches, require the candidate to
        # be shorter (broader scope) — avoids suggesting a more-specific topic
        # as a parent (e.g. "Python AST Visitor" should not parent "Python AST").
        if c_title_lower in title_lower:
            parent_ids.append(c["id"])
        elif c["score"] >= 0.65 and len(c_title_lower) < len(title_lower):
            parent_ids.append(c["id"])
    return parent_ids


def _check_concept_duplicate(title: str, topic_ids: List[int]) -> Optional[Tuple[str, str]]:
    """Check if a concept with the same or very similar title already exists.

    Returns:
        None if no duplicate found (safe to create).
        ('exact', message) if exact case-insensitive match found.
        ('fuzzy', message) if a very similar title found (warning only).
    """
    # --- Exact match (case-insensitive) ---
    existing = db.find_concept_by_title(title)
    if existing:
        return ("exact", _link_existing_concept(existing, topic_ids))

    # --- Fuzzy match (soft warning) ---
    candidates = db.search_concepts(title, limit=10)
    for candidate in candidates:
        sim = db._title_similarity(title, candidate["title"])
        if sim >= 0.85:
            return (
                "fuzzy",
                f"⚠️ Very similar concept exists: **{candidate['title']}** "
                f"(#{candidate['id']}, similarity {sim:.0%}). "
                f"Consider using `link_concept` or `update_concept` instead.",
            )

    return None


def _link_existing_concept(existing: Dict, topic_ids: List[int]) -> str:
    """Link an existing concept to any new topics it isn't already under.
    Returns a user-friendly message."""
    concept_id = existing["id"]
    existing_topic_ids = set(existing.get("topic_ids", []))
    new_links = [tid for tid in topic_ids if tid not in existing_topic_ids]

    if new_links:
        db.link_concept(concept_id, new_links)
        linked_topics = [db.get_topic(tid) for tid in new_links]
        linked_names = [t["title"] for t in linked_topics if t]
        return (
            f"Concept **{existing['title']}** already exists (#{concept_id}). "
            f"Linked to additional topic(s): {', '.join(linked_names)}."
        )
    else:
        return (
            f"Concept **{existing['title']}** already exists (#{concept_id}) "
            f"and is already linked to the requested topic(s). No changes made."
        )


def _handle_add_concept(params: Dict) -> Tuple[str, Any]:
    # Resolve topics first (same as before)
    topic_ids, created_topics = _resolve_topic_ids(params)

    # --- Dedup guard: check for existing concept with same/similar title ---
    dup_check = _check_concept_duplicate(params["title"], topic_ids)
    if dup_check:
        dup_type, dup_msg = dup_check
        if dup_type == "exact":
            # Exact match: reuse existing concept, don't create a new one
            existing = db.find_concept_by_title(params["title"])
            if existing:
                db.set_session("last_added_concept_id", str(existing["id"]))
            return ("reply", dup_msg)
        # Fuzzy match: warn but still create (soft warning)
        # The warning is appended to the success message below

    concept_id = db.add_concept(
        title=params["title"],
        description=params.get("description"),
        topic_ids=topic_ids or None,
        next_review_at=params.get("next_review_at"),
    )

    # Stash for AddConceptConfirmView (views.py/bot.py read this after execute)
    db.set_session("last_added_concept_id", str(concept_id))

    # Optional initial remark
    if params.get("remark"):
        db.add_remark(concept_id, params["remark"])

    topic_names = ""
    if topic_ids:
        topics = [db.get_topic(tid) for tid in topic_ids]
        names = [t["title"] for t in topics if t]
        topic_names = f" under {', '.join(names)}"

    created_note = ""
    if created_topics:
        created_strs = [f"'{t}' (#{tid})" for tid, t in created_topics]
        plural = "s" if len(created_topics) > 1 else ""
        created_note = f" (auto-created topic{plural}: {', '.join(created_strs)})"

    result = (
        f"Added concept **{params['title']}** (#{concept_id}){topic_names}{created_note}. "
        f"First review scheduled for tomorrow."
    )

    # Append fuzzy warning if applicable
    if dup_check and dup_check[0] == "fuzzy":
        result += f"\n\n{dup_check[1]}"

    return ("reply", result)


def _handle_update_concept(params: Dict) -> Tuple[str, Any]:
    cid = params.get("concept_id")
    if not cid:
        # Try to find by title
        title = params.get("title")
        if title:
            matches = db.search_concepts(title, limit=1)
            if matches:
                cid = matches[0]["id"]
    if not cid:
        return ("error", "update_concept requires concept_id or a matchable title")

    # Extract updatable fields
    update_fields = {}
    for key in (
        "title",
        "description",
        "mastery_level",
        "ease_factor",
        "interval_days",
        "next_review_at",
        "last_reviewed_at",
        "review_count",
    ):
        if key in params and params[key] is not None:
            update_fields[key] = params[key]

    # Guard: maintenance must never manipulate score/scheduling fields.
    # Scores change only via the assess action during quiz sessions.
    SCORE_FIELDS = {
        "mastery_level",
        "ease_factor",
        "interval_days",
        "next_review_at",
        "last_reviewed_at",
        "review_count",
    }
    if get_action_source() == "maintenance":
        stripped = [k for k in SCORE_FIELDS if k in update_fields]
        if stripped:
            logger.warning(f"Blocked maintenance score manipulation on concept #{cid}: {stripped}")
            for k in stripped:
                del update_fields[k]

    # New title passed separately when it's for renaming
    if "new_title" in params:
        update_fields["title"] = params["new_title"]

    if update_fields:
        db.update_concept(int(cid), **update_fields)

    # Optional remark
    if params.get("remark"):
        db.add_remark(int(cid), params["remark"])

    return ("reply", f"Updated concept #{cid}")


def _handle_delete_concept(params: Dict) -> Tuple[str, Any]:
    cid = params.get("concept_id")
    if not cid:
        return ("error", "delete_concept requires concept_id")

    concept = db.get_concept(int(cid))
    if not concept:
        return ("error", f"Concept #{cid} not found")

    db.delete_concept(int(cid))
    return ("reply", f"Deleted concept **{concept['title']}** (#{cid})")


def _handle_link_concept(params: Dict) -> Tuple[str, Any]:
    cid = params.get("concept_id")
    topic_ids = params.get("topic_ids", [])
    if isinstance(topic_ids, int):
        topic_ids = [topic_ids]
    if not cid or not topic_ids:
        return ("error", "link_concept requires concept_id and topic_ids")

    count = db.link_concept(int(cid), topic_ids)
    return ("reply", f"Linked concept #{cid} to {count} topic(s)")


def _handle_unlink_concept(params: Dict) -> Tuple[str, Any]:
    cid = params.get("concept_id")
    tid = params.get("topic_id")
    if not cid or not tid:
        return ("error", "unlink_concept requires concept_id and topic_id")

    ok = db.unlink_concept(int(cid), int(tid))
    if ok:
        return ("reply", f"Unlinked concept #{cid} from topic #{tid}")
    return ("error", f"No link found between concept #{cid} and topic #{tid}")


def _handle_remark(params: Dict) -> Tuple[str, Any]:
    cid = params.get("concept_id")
    content = params.get("content")

    if not cid:
        # Try by title
        title = params.get("title")
        if title:
            matches = db.search_concepts(title, limit=1)
            if matches:
                cid = matches[0]["id"]
    if not cid:
        return ("error", "remark requires concept_id or a matchable title")
    if not content:
        return ("error", "remark requires content")

    db.add_remark(int(cid), content)
    return ("reply", f"Added remark to concept #{cid}")


def _handle_remove_relation(params: Dict) -> Tuple[str, Any]:
    a = params.get("concept_id_a")
    b = params.get("concept_id_b")
    if not a or not b:
        return ("error", "remove_relation requires concept_id_a and concept_id_b")
    ok = db.remove_relation(int(a), int(b))
    if ok:
        return ("reply", f"Removed relation between concept #{a} and #{b}")
    return ("error", f"No relation found between concept #{a} and #{b}")


# ============================================================================
# Quiz / Assess Handlers
# ============================================================================


# ============================================================================
# Fetch Cluster (multi-concept quiz context)
# ============================================================================


def _handle_fetch_cluster(params: Dict) -> Tuple[str, Any]:
    """Fetch a primary concept + semantically related concepts for multi-concept quiz.

    Uses vector store nearest-neighbor search to find related concepts.
    Biases toward concepts that are also due for review when possible.
    Returns the primary concept detail plus 2–3 related concept details.
    """
    primary_id = int(params["concept_id"])
    limit = int(params.get("cluster_size", 3))

    primary = db.get_concept_detail(primary_id)
    if not primary:
        return ("fetch", {"error": f"Concept #{primary_id} not found"})

    cluster_concepts = [primary]

    # Try vector-based clustering
    try:
        if db.VECTORS_AVAILABLE:
            neighbors = db.find_nearest_concepts(
                primary_id,
                limit=limit * 2,
                score_threshold=0.4,
            )

            if neighbors:
                # Bias toward due concepts
                due_concepts = db.get_due_concepts(limit=50)
                due_ids = {c["id"] for c in due_concepts}

                # Sort: due concepts first, then by similarity
                neighbors.sort(
                    key=lambda n: (
                        0 if n["id"] in due_ids else 1,
                        -n["score"],
                    )
                )

                # Take top N
                for neighbor in neighbors[:limit]:
                    detail = db.get_concept_detail(neighbor["id"])
                    if detail:
                        detail["cluster_similarity"] = neighbor["score"]
                        cluster_concepts.append(detail)
    except Exception as e:
        logger.warning(f"[fetch_cluster] Vector search failed: {e}")

    # Fallback: if no vector results, use explicit relations
    if len(cluster_concepts) < 2:
        relations = db.get_relations(primary_id)
        for rel in relations[:limit]:
            related_id = (
                rel["concept_id_b"]
                if rel.get("concept_id_a") == primary_id
                else rel.get("concept_id_a", rel.get("concept_id_low"))
            )
            if related_id and related_id != primary_id:
                detail = db.get_concept_detail(related_id)
                if detail:
                    cluster_concepts.append(detail)
                if len(cluster_concepts) > limit:
                    break

    return (
        "fetch",
        {
            "concept_cluster": cluster_concepts,
            "primary_concept_id": primary_id,
            "cluster_size": len(cluster_concepts),
        },
    )


# ============================================================================
# Action Handler Map
# ============================================================================


def execute_suggest_topic_accept(action_data: dict) -> tuple[bool, str, int | None]:
    """Compatibility wrapper for the suggest-topic confirm flow."""
    from services.tools_assess import execute_suggest_topic_accept as _accept

    return _accept(action_data)


def _handle_none(params: Dict) -> Tuple[str, Any]:
    """Pass-through for pure conversational replies where the LLM
    chose action='none' or action='reply' — no DB side-effects."""
    return ("reply", params.get("message", ""))


# Import assessment/quiz handlers from extracted module
from services.tools_assess import (  # noqa: E402
    _handle_assess,
    _handle_multi_assess,
    _handle_multi_quiz,
    _handle_quiz,
    _handle_suggest_topic,
)

ACTION_HANDLERS = {
    "none": _handle_none,
    "reply": _handle_none,
    "fetch": _handle_fetch,
    "add_topic": _handle_add_topic,
    "update_topic": _handle_update_topic,
    "delete_topic": _handle_delete_topic,
    "link_topics": _handle_link_topics,
    "unlink_topics": _handle_unlink_topics,
    "list_topics": _handle_list_topics,
    "add_concept": _handle_add_concept,
    "update_concept": _handle_update_concept,
    "delete_concept": _handle_delete_concept,
    "link_concept": _handle_link_concept,
    "unlink_concept": _handle_unlink_concept,
    "remark": _handle_remark,
    "remove_relation": _handle_remove_relation,
    "quiz": _handle_quiz,
    "multi_quiz": _handle_multi_quiz,
    "assess": _handle_assess,
    "multi_assess": _handle_multi_assess,
    "suggest_topic": _handle_suggest_topic,
}
