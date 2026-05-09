"""Shared review quiz generation helpers.

This module owns review payload/check helpers plus the structured quiz
generation and delivery-formatting flow, without taking ownership of review
delivery, reminder persistence, or transport-specific UI decisions.
"""

from dataclasses import dataclass
import json
import logging

import config
import db
from services import context as ctx
from services import llm_runtime, pipeline
from services.chat_payload import build_chat_payload
from services.llm import LLMError, get_reasoning_provider
from services.parser import _extract_json_object, parse_llm_response, process_output
from services.review_state import bind_single_quiz_context
from services.tools import set_action_source


logger = logging.getLogger("review_flow")


_QUIZ_GENERATOR_SKILL = ctx.SKILLS_DIR / "quiz_generator.md"
_QUIZ_QUESTION_TYPES = {
    "definition",
    "mechanism",
    "comparison",
    "application",
    "synthesis",
    "edge-case",
    "teach-back",
}


call_with_fetch_loop = llm_runtime.call_with_fetch_loop


@dataclass(frozen=True)
class ReviewQuizResult:
    concept_id: int | None
    message: str
    action_data: dict | None
    choices: list[str]

    def assess_meta(self) -> dict | None:
        if not self.action_data:
            return None
        if self.action_data.get("action", "").lower().strip() != "assess":
            return None
        params = self.action_data.get("params", {})
        quality = params.get("quality")
        if quality is None:
            return None
        return {
            "concept_id": params.get("concept_id", self.concept_id),
            "quality": quality,
        }

    def to_chat_payload(
        self,
        *,
        quiz_actions: list[dict] | None = None,
    ) -> dict:
        return build_chat_payload(self.message, actions=quiz_actions)

    def to_discord_result(self) -> tuple[str, dict | None, dict | None, dict | None]:
        assess_meta = self.assess_meta()
        message = self.message
        quiz_meta = None
        if assess_meta is not None:
            message = f"📚 **Learning Review**\n{message}"
        elif self.concept_id is not None:
            quiz_meta = {
                "concept_id": self.concept_id,
                "heading": "📚 **Learning Review**",
            }
        return message, None, assess_meta, quiz_meta


def parse_review_payload_concept_id(payload: str) -> int | None:
    try:
        return int(payload.split("|", 1)[0])
    except (ValueError, IndexError):
        return None


def build_review_payload(concept_id: int) -> str | None:
    """Build the canonical review payload for one concept."""
    detail = db.get_concept_detail(concept_id)
    if not detail:
        return None

    topic_names = [topic["title"] for topic in detail.get("topics", [])]
    recent_reviews = detail.get("recent_reviews", [])
    remark_summary = detail.get("remark_summary", "")

    context_parts = [
        f"Concept: {detail['title']} (#{detail['id']})",
        f"Description: {detail.get('description', 'N/A')}",
        f"Topics: {', '.join(topic_names) if topic_names else 'untagged'}",
        f"Score: {detail['mastery_level']}/100, Reviews: {detail['review_count']}",
    ]

    if remark_summary:
        context_parts.append(f"Latest remark: {remark_summary[:100]}")

    if recent_reviews:
        last = recent_reviews[0]
        context_parts.append(f"Last Q: {last.get('question_asked', 'N/A')}")
        context_parts.append(f"Last quality: {last.get('quality', 'N/A')}/5")

    return f"{detail['id']}|{' | '.join(context_parts)}"


def handle_review_check() -> list[str]:
    """Find due concepts and return review payload strings.

    Falls back to the nearest upcoming concept if nothing is overdue.
    """
    due = db.get_due_concepts(limit=5)
    if due:
        concept = due[0]
    else:
        concept = db.get_next_review_concept()
        if not concept:
            return []

    payload = build_review_payload(int(concept["id"]))
    if not payload:
        return []

    if len(due) > 1:
        logger.info("%s more concept(s) due for review", len(due) - 1)

    return [payload]


def _quiz_generator_system_prompt() -> str:
    """Build Prompt 1 instructions with persona guidance for delivery text."""
    system_prompt = ctx._read_file(_QUIZ_GENERATOR_SKILL)
    if not system_prompt:
        return ""

    persona_content = db.get_persona_content(db.get_persona())
    preferences_content = ctx._read_file(ctx.PREFERENCES_MD_PATH)

    parts = [system_prompt]
    if persona_content:
        parts.append(f"## Active Persona\n\n{persona_content}")
    if preferences_content:
        parts.append(f"## User Preferences\n\n{preferences_content}")
    parts.append(
        "Use the active persona only when writing `formatted_question`. "
        "Keep `reasoning` analytical and concise."
    )
    return "\n\n".join(parts)


def _validate_quiz_generator_result(result: dict) -> dict:
    """Validate and normalize Prompt 1 structured output."""
    if not isinstance(result, dict):
        raise LLMError("Reasoning model output must be a JSON object", retryable=True)

    question = result.get("question")
    if not isinstance(question, str) or not question.strip():
        raise LLMError("Reasoning model output missing valid 'question' field", retryable=True)

    formatted_question = result.get("formatted_question")
    if not isinstance(formatted_question, str) or not formatted_question.strip():
        raise LLMError(
            "Reasoning model output missing valid 'formatted_question' field",
            retryable=True,
        )

    difficulty = result.get("difficulty")
    if not isinstance(difficulty, int) or not 0 <= difficulty <= 100:
        raise LLMError("Reasoning model output has invalid 'difficulty' field", retryable=True)

    question_type = result.get("question_type")
    if question_type not in _QUIZ_QUESTION_TYPES:
        raise LLMError("Reasoning model output has invalid 'question_type' field", retryable=True)

    target_facet = result.get("target_facet")
    if not isinstance(target_facet, str) or not target_facet.strip():
        raise LLMError("Reasoning model output missing valid 'target_facet' field", retryable=True)

    reasoning = result.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise LLMError("Reasoning model output missing valid 'reasoning' field", retryable=True)

    concept_ids = result.get("concept_ids")
    if (
        not isinstance(concept_ids, list)
        or not concept_ids
        or not all(isinstance(cid, int) for cid in concept_ids)
    ):
        raise LLMError("Reasoning model output has invalid 'concept_ids' field", retryable=True)

    choices = result.get("choices")
    if choices is not None:
        if (
            not isinstance(choices, list)
            or not choices
            or not all(isinstance(choice, str) and choice.strip() for choice in choices)
        ):
            raise LLMError("Reasoning model output has invalid 'choices' field", retryable=True)

    return result


def format_quiz_action(p1_result: dict, concept_id: int) -> str:
    """Deterministically format a P1 quiz result for review delivery."""
    del concept_id
    message = (p1_result.get("formatted_question") or p1_result.get("question") or "").strip()
    if not message:
        raise LLMError("Quiz formatter requires a non-empty question", retryable=False)
    return f"REPLY: {message}"


async def generate_quiz_question(concept_id: int) -> dict:
    """Prompt 1: Use the reasoning model to generate a quiz question."""
    quiz_context = ctx.build_quiz_generator_context(concept_id)
    if not quiz_context:
        raise LLMError(f"Concept {concept_id} not found", retryable=False)

    system_prompt = _quiz_generator_system_prompt()
    if not system_prompt:
        raise LLMError("quiz_generator.md not found", retryable=False)

    prompt = (
        f"{quiz_context}\n\n"
        f"Generate a quiz question for the primary concept above. "
        f"Respond with a single JSON object only."
    )

    provider = get_reasoning_provider()
    raw = await provider.send(
        prompt,
        system_prompt=system_prompt,
        response_format={"type": "json_object"},
        timeout=config.COMMAND_TIMEOUT,
    )

    if not raw:
        raise LLMError("Empty response from reasoning provider", retryable=True)

    try:
        text = raw.strip()
        result = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        result = _extract_json_object(raw)
        if result is None:
            logger.error("P1 returned unparseable JSON: %s", raw[:300])
            raise LLMError(f"Reasoning model returned invalid JSON: {exc}", retryable=True)

    result = _validate_quiz_generator_result(result)

    logger.info(
        "P1 generated question for concept #%s: type=%s, diff=%s",
        concept_id,
        result.get("question_type"),
        result.get("difficulty"),
    )

    db.set_session("p1_question_type", result.get("question_type"))
    db.set_session("p1_target_facet", result.get("target_facet"))
    difficulty = result.get("difficulty")
    db.set_session("p1_difficulty", str(difficulty) if difficulty is not None else None)

    try:
        db.update_concept(concept_id, last_quiz_generator_output=json.dumps(result))
    except Exception as exc:
        logger.warning("Failed to cache P1 output for concept %s: %s", concept_id, exc)

    return result


async def generate_review_quiz_from_payload(
    payload: str,
    *,
    author: str,
    source: str,
    track_in_progress: bool,
) -> ReviewQuizResult:
    """Generate a review quiz message from a review payload.

    This owns the repeated quiz-generation sequence used by chat, Discord, and
    scheduler flows. Callers still own message delivery and any pending-review
    persistence that must happen only after successful delivery.
    """
    review_text = f"[SCHEDULED_REVIEW] Start a review quiz for this concept: {payload}"
    concept_id = parse_review_payload_concept_id(payload)

    if concept_id is not None:
        bind_single_quiz_context(concept_id)

    if track_in_progress:
        db.set_session("review_in_progress", str(concept_id) if concept_id else "1")

    set_action_source(source)

    p1_result = None
    try:
        try:
            if concept_id is not None:
                p1_result = await generate_quiz_question(concept_id)
                llm_response = format_quiz_action(p1_result, concept_id)
            else:
                raise LLMError("No concept_id in payload", retryable=True)
        except LLMError:
            llm_response = await call_with_fetch_loop(
                mode="review-check",
                text=review_text,
                author=author,
            )

        final_result = await pipeline.execute_llm_response(review_text, llm_response, "reply")
        _msg_type, response = process_output(final_result)
        message = response.strip() if response else "Could not generate a review quiz. Try again?"
        if concept_id is not None:
            bind_single_quiz_context(concept_id, question=message)
        else:
            db.set_session("last_quiz_question", message)

        _prefix, _message, action_data = parse_llm_response(llm_response)
        raw_choices = []
        if isinstance(p1_result, dict):
            raw_choices = p1_result.get("choices") or []
        choices = [str(choice).strip() for choice in raw_choices if str(choice).strip()]
        return ReviewQuizResult(
            concept_id=concept_id,
            message=message,
            action_data=action_data,
            choices=choices,
        )
    finally:
        if track_in_progress:
            db.set_session("review_in_progress", None)