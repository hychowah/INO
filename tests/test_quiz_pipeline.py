import json
from unittest.mock import AsyncMock, patch

import pytest

from services.llm import LLMError
from services.pipeline import (
    _quiz_generator_system_prompt,
    format_quiz_action,
    package_quiz_for_discord,
)


def test_format_quiz_action_prefers_formatted_question():
    result = format_quiz_action(
        {
            "question": "What does ASGI stand for?",
            "formatted_question": (
                "Let's zoom in: what does ASGI stand for, and why does it matter here?"
            ),
        },
        7,
    )

    assert result.startswith("REPLY: Let's zoom in:")


def test_quiz_generator_system_prompt_includes_preferences_and_persona():
    with (
        patch("services.pipeline.ctx._read_file", side_effect=["skill prompt", "pref body"]),
        patch("services.pipeline.get_persona", return_value="mentor"),
        patch("services.pipeline.get_persona_content", return_value="persona body"),
    ):
        prompt = _quiz_generator_system_prompt()

    assert "skill prompt" in prompt
    assert "## Active Persona" in prompt
    assert "persona body" in prompt
    assert "## User Preferences" in prompt
    assert "pref body" in prompt


@pytest.mark.anyio
async def test_package_quiz_for_discord_uses_deterministic_formatter():
    result = await package_quiz_for_discord(
        {
            "question": "What does ASGI stand for?",
            "formatted_question": "Quick check: what does ASGI stand for?",
        },
        7,
    )

    assert result == "REPLY: Quick check: what does ASGI stand for?"


@pytest.mark.anyio
async def test_generate_quiz_question_requests_json_response_format():
    provider = AsyncMock()
    provider.send = AsyncMock(
        return_value=json.dumps(
            {
                "question": "What problem does FastAPI solve?",
                "formatted_question": "Quick check: what problem does FastAPI solve in the stack?",
                "difficulty": 35,
                "question_type": "definition",
                "target_facet": "framework purpose",
                "reasoning": "Low-score concept, so ask for the core role first.",
                "concept_ids": [12],
            }
        )
    )

    with (
        patch("services.pipeline.ctx.build_quiz_generator_context", return_value="context"),
        patch("services.pipeline._quiz_generator_system_prompt", return_value="sys"),
        patch("services.pipeline.get_reasoning_provider", return_value=provider),
        patch("services.pipeline.db.update_concept") as update_concept,
        patch("services.pipeline.db.set_session") as set_session,
    ):
        from services.pipeline import generate_quiz_question

        result = await generate_quiz_question(12)

    assert result["formatted_question"].startswith("Quick check:")
    assert provider.send.await_args.kwargs["response_format"] == {"type": "json_object"}
    set_session.assert_any_call("p1_question_type", "definition")
    set_session.assert_any_call("p1_target_facet", "framework purpose")
    set_session.assert_any_call("p1_difficulty", "35")
    update_concept.assert_called_once()
    assert update_concept.call_args.kwargs["last_quiz_generator_output"]


@pytest.mark.anyio
async def test_generate_quiz_question_rejects_missing_formatted_question():
    provider = AsyncMock()
    provider.send = AsyncMock(
        return_value=json.dumps(
            {
                "question": "What problem does FastAPI solve?",
                "difficulty": 35,
                "question_type": "definition",
                "target_facet": "framework purpose",
                "reasoning": "Low-score concept, so ask for the core role first.",
                "concept_ids": [12],
            }
        )
    )

    with (
        patch("services.pipeline.ctx.build_quiz_generator_context", return_value="context"),
        patch("services.pipeline._quiz_generator_system_prompt", return_value="sys"),
        patch("services.pipeline.get_reasoning_provider", return_value=provider),
    ):
        from services.pipeline import generate_quiz_question

        with pytest.raises(LLMError, match="formatted_question"):
            await generate_quiz_question(12)
