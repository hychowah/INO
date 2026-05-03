"""Shared review quiz generation helpers.

This module keeps the first extraction slice intentionally small: it centralizes
the repeated "payload -> quiz message" flow without taking ownership of review
delivery, reminder persistence, or transport-specific UI decisions.
"""

from dataclasses import dataclass

import db
from services import pipeline
from services.llm import LLMError
from services.parser import parse_llm_response
from services.review_state import bind_single_quiz_context
from services.tools import set_action_source


@dataclass(frozen=True)
class ReviewQuizResult:
    concept_id: int | None
    message: str
    action_data: dict | None
    choices: list[str]


def parse_review_payload_concept_id(payload: str) -> int | None:
    try:
        return int(payload.split("|", 1)[0])
    except (ValueError, IndexError):
        return None


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
                p1_result = await pipeline.generate_quiz_question(concept_id)
                llm_response = await pipeline.package_quiz_for_discord(p1_result, concept_id)
            else:
                raise LLMError("No concept_id in payload", retryable=True)
        except LLMError:
            llm_response = await pipeline.call_with_fetch_loop(
                mode="review-check",
                text=review_text,
                author=author,
            )

        final_result = await pipeline.execute_llm_response(review_text, llm_response, "reply")
        _msg_type, response = pipeline.process_output(final_result)
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