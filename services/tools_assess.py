"""
Assessment and quiz action handlers, extracted from services/tools.py.
"""

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple

import config
import db
from services.tools import execute_action

logger = logging.getLogger("tools")


# ============================================================================
# Quiz handlers
# ============================================================================


def _handle_quiz(params: Dict) -> Tuple[str, Any]:
    """The quiz action is special: the LLM generates the question text itself.
    This action just records that a quiz was started and returns metadata
    so the LLM can reference it in subsequent assess calls."""
    cid = params.get("concept_id")
    message = params.get("message", "Quiz question sent.")

    # Anchor quiz concept in session state so assess fallback and context
    # injection use the correct concept even if fetch overwrites
    # active_concept_id mid-loop.  See DEVNOTES §16.
    if cid is not None:
        db.set_session("active_concept_id", str(cid))
        db.set_session("quiz_anchor_concept_id", str(cid))
        logger.debug(f"[quiz_anchor] SET to concept #{cid} by _handle_quiz")
        message += f"\n_(quiz on concept #{cid})_"

    return ("reply", message)


def _handle_multi_quiz(params: Dict) -> Tuple[str, Any]:
    """Multi-concept quiz: the LLM asks a question spanning multiple concepts.
    Records all concept IDs in session state for multi_assess to pick up."""
    concept_ids = params.get("concept_ids", [])
    message = params.get("message", "Multi-concept quiz question sent.")

    if not concept_ids or len(concept_ids) < 2:
        return ("error", "multi_quiz requires concept_ids with at least 2 IDs")

    # Validate all concepts exist
    valid_ids = []
    for cid in concept_ids:
        concept = db.get_concept(int(cid))
        if concept:
            valid_ids.append(int(cid))
        else:
            logger.warning(f"[multi_quiz] Concept #{cid} not found, skipping")

    if len(valid_ids) < 2:
        return ("error", "multi_quiz: need at least 2 valid concept_ids")

    # Store in session state for multi_assess
    db.set_session("active_concept_ids", json.dumps(valid_ids))
    db.set_session("active_concept_id", str(valid_ids[0]))  # primary
    # Clear any single-quiz anchor — mutually exclusive states (§16)
    db.set_session("quiz_anchor_concept_id", None)

    # Embed concept IDs in message for chat history
    ids_str = ", ".join(f"#{cid}" for cid in valid_ids)
    message += f"\n_(multi-concept quiz on concepts {ids_str})_"

    return ("reply", message)


# ============================================================================
# Assess handlers
# ============================================================================


def _handle_multi_assess(params: Dict) -> Tuple[str, Any]:
    """Assess a multi-concept quiz answer. Scores each concept individually.

    Expects params:
      assessments: [{concept_id, quality, question_difficulty}, ...]
      llm_assessment: str — unified feedback text
      question_asked: str
      user_response: str
      message: str (optional — display text)
    """
    assessments = params.get("assessments", [])
    llm_assessment = params.get("llm_assessment", params.get("assessment", ""))
    question = params.get("question_asked", "")
    user_response = params.get("user_response", "")

    # Prefer the actual question text stored at send time over LLM echo
    stored_question = db.get_session("last_quiz_question")
    if stored_question and len(stored_question) > len(question):
        question = stored_question

    if not assessments:
        return ("error", "multi_assess requires 'assessments' list")

    results = []
    all_concept_names = []

    for entry in assessments:
        cid = entry.get("concept_id")
        quality = entry.get("quality")
        question_difficulty = entry.get("question_difficulty")

        if cid is None or quality is None:
            results.append("Skipped entry (missing concept_id or quality)")
            continue

        cid = int(cid)
        quality = max(0, min(5, int(quality)))

        concept = db.get_concept(cid)
        if not concept:
            results.append(f"Concept #{cid} not found")
            continue

        current_score = concept.get("mastery_level", 0)

        if question_difficulty is not None:
            question_difficulty = max(0, min(100, int(question_difficulty)))
        else:
            if quality >= 4:
                question_difficulty = min(100, current_score + 10)
            elif quality == 3:
                question_difficulty = current_score
            else:
                question_difficulty = min(100, current_score + 15)

        # Score delta calculation (same formula as single assess)
        gap = question_difficulty - current_score

        if quality >= 3:
            base_gain = {3: 2, 4: 4, 5: 7}[quality]
            if gap > 0:
                delta = base_gain + gap * 0.15
            else:
                delta = max(1, base_gain * 0.5)
            new_score = min(100, round(current_score + delta))
        else:
            base_loss = {0: 5, 1: 3, 2: 1}[quality]
            if gap > 0:
                delta = 0
            else:
                delta = base_loss + abs(gap) * 0.2
            new_score = max(0, round(current_score - delta))

        new_interval = max(1, round(math.exp(new_score * config.SR_INTERVAL_EXPONENT)))

        now = datetime.now()
        next_review = (now + timedelta(days=new_interval)).strftime("%Y-%m-%d %H:%M:%S")

        db.update_concept(
            cid,
            mastery_level=new_score,
            interval_days=new_interval,
            next_review_at=next_review,
            last_reviewed_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            review_count=concept.get("review_count", 0) + 1,
        )

        db.add_review(cid, question, user_response, quality, llm_assessment)

        if entry.get("remark"):
            db.add_remark(cid, entry["remark"])

        score_change = new_score - current_score
        sign = "+" if score_change >= 0 else ""
        results.append(
            f"#{cid} {concept['title']}: q{quality}/5, "
            f"{current_score}→{new_score} ({sign}{score_change}), "
            f"next in {new_interval}d"
        )
        all_concept_names.append(concept["title"])

    # Clear multi-concept session state
    db.set_session("active_concept_ids", None)
    db.set_session("active_concept_id", None)
    db.set_session("pending_review", None)

    default_msg = f"Multi-assess ({len(results)} concepts):\n" + "\n".join(results)
    return ("reply", params.get("message", default_msg))


def _handle_assess(params: Dict) -> Tuple[str, Any]:
    """Record the LLM's assessment of a user's answer.
    Updates concept score (0-100), logs the review, and schedules next review.

    Score system: asymmetric deltas based on question_difficulty vs current score.
    - Correct on hard question (above level): big gain
    - Correct on easy question (at/below): small reinforcement
    - Wrong on hard question (above level): NO penalty (probe above level)
    - Wrong on easy question (at/below): proportional loss

    Interval: exponential from score — interval = e^(score * 0.05) days.
    """
    cid = params.get("concept_id")
    quality = params.get("quality")
    question_difficulty = params.get("question_difficulty")
    assessment = params.get("assessment", "")
    question = params.get("question_asked", "")
    user_response = params.get("user_response", "")

    # Prefer the actual question text stored at send time over LLM echo,
    # which may be truncated or paraphrased
    stored_question = db.get_session("last_quiz_question")
    if stored_question and len(stored_question) > len(question):
        question = stored_question

    if cid is None or quality is None:
        return ("error", "assess requires concept_id and quality (0-5)")

    cid = int(cid)
    quality = max(0, min(5, int(quality)))

    # Default question_difficulty to a reasonable estimate if LLM omits it
    if question_difficulty is not None:
        question_difficulty = max(0, min(100, int(question_difficulty)))

    # Get current concept state
    concept = db.get_concept(cid)
    if not concept:
        # Fallback 1: quiz anchor (sacred, protected from fetch overwrites)
        anchor_cid = db.get_session("quiz_anchor_concept_id")
        if anchor_cid:
            concept = db.get_concept(int(anchor_cid))
            if concept:
                cid = int(anchor_cid)

    if not concept:
        # Fallback 2: active_concept_id (may have been overwritten by fetch)
        active_cid = db.get_session("active_concept_id")
        if active_cid:
            concept = db.get_concept(int(active_cid))
            if concept:
                cid = int(active_cid)

    if not concept:
        # Fallback 3: search chat history for the last quiz concept_id
        history = db.get_chat_history(limit=6)
        import re

        for msg in reversed(history):
            m = re.search(r"quiz on concept #(\d+)", msg.get("content", ""))
            if m:
                fallback_cid = int(m.group(1))
                concept = db.get_concept(fallback_cid)
                if concept:
                    cid = fallback_cid
                    break
        if not concept:
            return ("error", f"Concept #{cid} not found")

    current_score = concept.get("mastery_level", 0)

    # If LLM didn't provide question_difficulty, estimate from current score
    # and quality: good answer → question was near their level,
    # bad answer → question was somewhat above their level
    if question_difficulty is None:
        if quality >= 4:
            question_difficulty = min(100, current_score + 10)
        elif quality == 3:
            question_difficulty = current_score
        else:
            question_difficulty = min(100, current_score + 15)

    # --- Score delta calculation ---
    gap = question_difficulty - current_score  # positive = above level

    if quality >= 3:
        # CORRECT — gain points
        base_gain = {3: 2, 4: 4, 5: 7}[quality]
        if gap > 0:
            # Above level: rewarded for stretching
            delta = base_gain + gap * 0.15
        else:
            # At/below level: small reinforcement
            delta = max(1, base_gain * 0.5)
        new_score = min(100, round(current_score + delta))
    else:
        # WRONG — only penalize if question was at/below user's level
        base_loss = {0: 5, 1: 3, 2: 1}[quality]
        if gap > 0:
            # Above level: NO penalty — LLM probed beyond user's level
            delta = 0
        else:
            # At/below level: proportional regression
            delta = base_loss + abs(gap) * 0.2
        new_score = max(0, round(current_score - delta))

    # --- Interval from score: exponential curve ---
    # score 0→1d, 25→3d, 50→12d, 75→43d, 100→148d  (at default exponent 0.05)
    new_interval = max(1, round(math.exp(new_score * config.SR_INTERVAL_EXPONENT)))

    now = datetime.now()
    next_review = (now + timedelta(days=new_interval)).strftime("%Y-%m-%d %H:%M:%S")

    # Update concept (mastery_level stores score 0-100 now)
    db.update_concept(
        cid,
        mastery_level=new_score,
        interval_days=new_interval,
        next_review_at=next_review,
        last_reviewed_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        review_count=concept.get("review_count", 0) + 1,
    )

    # Stash for QuizNavigationView (bot.py reads these after execute)
    db.set_session("last_assess_concept_id", str(cid))
    db.set_session("last_assess_quality", str(quality))

    # Clear pending review state — the quiz has been answered
    db.set_session("pending_review", None)

    # Log the review
    db.add_review(cid, question, user_response, quality, assessment)

    # Add remark if provided
    if params.get("remark"):
        db.add_remark(cid, params["remark"])

    # Auto-create concept relationships if LLM identified related concepts
    related_ids = params.get("related_concept_ids")
    if related_ids and isinstance(related_ids, list):
        rel_type = params.get("relation_type", "builds_on")
        if rel_type not in db.VALID_RELATION_TYPES:
            rel_type = "builds_on"
        added = db.add_relations_from_assess(cid, related_ids, rel_type)
        if added:
            logger.info(f"[assess] Auto-linked {added} related concept(s) for #{cid}")

    score_change = new_score - current_score
    sign = "+" if score_change >= 0 else ""
    return (
        "reply",
        params.get(
            "message",
            f"Assessed concept #{cid}: quality {quality}/5, "
            f"score {current_score}→{new_score} ({sign}{score_change}), "
            f"next review in {new_interval} day(s)",
        ),
    )


# ============================================================================
# Suggest Topic (from casual Q&A)
# ============================================================================


def execute_suggest_topic_accept(action_data: dict) -> tuple[bool, str, int | None]:
    """Execute a confirmed suggest_topic: create topic + initial concepts.

    Called by both SuggestTopicConfirmView.accept() and the text-reply handler
    in bot.py — single source of truth for the multi-step create flow.

    Returns (success, summary_message, topic_id).
    Handles partial failures gracefully.
    """
    import re as _re

    params = action_data.get("params", {})
    title = params.get("title", "Untitled")
    description = params.get("description", "")
    concepts = params.get("concepts", [])
    parent_ids = params.get("parent_ids", [])
    if isinstance(parent_ids, int):
        parent_ids = [parent_ids]

    # 1. Create the topic (with parent linkage if specified)
    add_params = {"title": title, "description": description}
    if parent_ids:
        add_params["parent_ids"] = parent_ids
    msg_type, result = execute_action("add_topic", add_params)
    if msg_type == "error":
        return False, f"Could not create topic: {result}", None

    # 2. Retrieve topic_id from session stash (set by _handle_add_topic)
    topic_id_str = db.get_session("last_added_topic_id")
    if topic_id_str:
        topic_id = int(topic_id_str)
    else:
        # Fallback: parse from result string
        m = _re.search(r"#(\d+)", str(result))
        topic_id = int(m.group(1)) if m else None

    if not topic_id:
        return False, f"Topic created but could not determine ID: {result}", None

    # 3. Create each proposed concept under the new topic
    created = []
    failed = []
    for c in concepts:
        if not isinstance(c, dict):
            continue
        c_title = c.get("title", "")
        if not c_title:
            continue
        c_type, c_result = execute_action(
            "add_concept",
            {
                "title": c_title,
                "description": c.get("description", ""),
                "topic_ids": [topic_id],
            },
        )
        if c_type == "error":
            failed.append(c_title)
        else:
            created.append(c_result)

    # 4. Build summary
    parts = [f"Created topic **{title}** (#{topic_id})"]
    if created:
        parts.append(f"with {len(created)} concept(s)")
    if failed:
        parts.append(f"({len(failed)} failed: {', '.join(failed)})")

    summary = "✅ " + " ".join(parts)
    return True, summary, topic_id


def _handle_suggest_topic(params: Dict) -> Tuple[str, Any]:
    """LLM suggests creating a topic + concepts from a casual conversation.
    This just formats the suggestion — actual creation happens when user confirms
    via add_topic + add_concept actions in a follow-up turn."""
    title = params.get("title", "")
    description = params.get("description", "")
    concepts = params.get("concepts", [])
    parent_ids = params.get("parent_ids", [])
    if isinstance(parent_ids, int):
        parent_ids = [parent_ids]

    lines = [f"💡 I could track **{title}** as a learning topic."]
    if parent_ids:
        parent_names = []
        for pid in parent_ids:
            pt = db.get_topic(int(pid))
            if pt:
                parent_names.append(pt["title"])
        if parent_names:
            lines.append(f"(under {', '.join(parent_names)})")
    if description:
        lines.append(f"_{description}_")
    if concepts:
        lines.append("\nInitial concepts I'd add:")
        for c in concepts:
            if isinstance(c, dict):
                lines.append(f"  • **{c.get('title', '')}** — {c.get('description', '')}")
            else:
                lines.append(f"  • {c}")
    lines.append("\nWant me to add this to your learning list?")

    return ("reply", "\n".join(lines))


def skip_quiz(concept_id: int, user_id: str = "default") -> dict:
    """Skip a quiz question without answering. Scores as quality=5 with
    synthetic difficulty, writes a synthetic remark, and logs the review.

    Only allowed when the concept has review_count >= 2 (anti-gaming guard).
    Returns dict with {concept_id, title, old_score, new_score, interval_days}
    or {error: str} on failure.
    """
    concept = db.get_concept(concept_id)
    if not concept:
        return {"error": f"Concept #{concept_id} not found"}

    if concept.get("review_count", 0) < 2:
        return {"error": "Need at least 2 reviews before skipping"}

    # Race guard: prevent double-processing if user already answered
    if db.get_session("quiz_answered"):
        db.set_session("quiz_answered", None)
        return {"error": "Quiz already answered or skipped"}

    current_score = concept.get("mastery_level", 0)
    old_interval = concept.get("interval_days", 1)

    # Score using normal quality=5 algorithm with synthetic difficulty
    question_difficulty = min(100, current_score + 10)
    gap = question_difficulty - current_score  # 10 or less at cap
    base_gain = 7  # quality=5
    delta = base_gain + gap * 0.15
    new_score = min(100, round(current_score + delta))

    # Interval from score: exponential curve
    new_interval = max(1, round(math.exp(new_score * config.SR_INTERVAL_EXPONENT)))

    now = datetime.now()
    next_review = (now + timedelta(days=new_interval)).strftime("%Y-%m-%d %H:%M:%S")

    db.update_concept(
        concept_id,
        mastery_level=new_score,
        interval_days=new_interval,
        next_review_at=next_review,
        last_reviewed_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        review_count=concept.get("review_count", 0) + 1,
    )

    # Log the review
    stored_question = db.get_session("last_quiz_question") or "(question not stored)"
    db.add_review(
        concept_id, stored_question, "[Skipped]", 5, "Skipped by user — claimed confident recall"
    )

    # Synthetic remark preserves LLM strategy continuity
    db.add_remark(
        concept_id,
        f"⏭️ Skipped — user claimed confident recall. "
        f"Score {current_score}→{new_score}, interval {old_interval}d→{new_interval}d.",
    )

    # Session vars for QuizNavigationView
    db.set_session("last_assess_concept_id", str(concept_id))
    db.set_session("last_assess_quality", "5")

    # Clean up session state
    db.set_session("pending_review", None)
    db.set_session("quiz_anchor_concept_id", None)
    db.set_session("last_quiz_question", None)
    db.set_session("quiz_answered", "1")

    # Audit trail
    db.log_action(
        action="skip_quiz",
        params={"concept_id": concept_id},
        result_type="reply",
        result=f"score {current_score}→{new_score}",
        source="discord",
        user_id=user_id,
    )

    logger.info(
        f"[skip_quiz] Concept #{concept_id} '{concept['title']}': "
        f"{current_score}→{new_score}, next in {new_interval}d"
    )

    return {
        "concept_id": concept_id,
        "title": concept["title"],
        "old_score": current_score,
        "new_score": new_score,
        "interval_days": new_interval,
    }
