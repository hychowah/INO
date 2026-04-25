import json
from unittest.mock import patch

import pytest

from services.parser import CONTROLLED_FORMAT_FAILURE_MESSAGE
from services.chat_session import _response
from services.pipeline import (
    _append_structured_output_hint,
    _main_response_format,
    _validate_or_retry_llm_output,
)

pytestmark = pytest.mark.unit


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.cleared = []

    async def send(
        self,
        prompt,
        *,
        session=None,
        system_prompt=None,
        response_format=None,
        timeout=120,
    ):
        self.sent.append(
            {
                "prompt": prompt,
                "session": session,
                "system_prompt": system_prompt,
                "response_format": response_format,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)

    def clear_session(self, session):
        self.cleared.append(session)


@pytest.mark.anyio
async def test_invalid_output_retries_once_and_clears_session():
    provider = FakeProvider(
        [
            (
                "The user is answering the quiz. Let me assess this.\n"
                '``json\n{"action": "assess", "params": {"concept_id": 1}, '
            ),
            "REPLY: Clean recovered answer.",
        ]
    )

    result = await _validate_or_retry_llm_output(
        provider=provider,
        raw=provider.responses.pop(0),
        original_text="model_validate?",
        system_prompt="system",
        session="learn_test",
        timeout=120,
    )

    assert result == "REPLY: Clean recovered answer."
    assert provider.cleared == ["learn_test"]
    assert len(provider.sent) == 1
    assert provider.sent[0]["session"] is None
    assert "violated the required output contract" in provider.sent[0]["prompt"]


@pytest.mark.anyio
async def test_invalid_output_returns_controlled_failure_after_retry_fails():
    provider = FakeProvider(
        [
            (
                "The user is answering the quiz.\n"
                '``json\n{"action": "assess", "params": {"concept_id": 1}, '
            )
        ]
    )

    result = await _validate_or_retry_llm_output(
        provider=provider,
        raw="<think>I should expose reasoning</think>",
        original_text="model_validate?",
        system_prompt="system",
        session="learn_test",
        timeout=120,
    )

    assert result == f"REPLY: {CONTROLLED_FORMAT_FAILURE_MESSAGE}"
    assert provider.cleared == ["learn_test"]
    assert len(provider.sent) == 1


@pytest.mark.anyio
async def test_valid_output_does_not_retry_or_clear_session():
    provider = FakeProvider([])

    result = await _validate_or_retry_llm_output(
        provider=provider,
        raw="REPLY: Already clean.",
        original_text="hello",
        system_prompt="system",
        session="learn_test",
        timeout=120,
    )

    assert result == "REPLY: Already clean."
    assert provider.cleared == []
    assert provider.sent == []


def test_main_response_format_uses_json_object_in_auto_mode():
    with patch("services.pipeline.config.LLM_OUTPUT_MODE", "auto"):
        assert _main_response_format() == {"type": "json_object"}


def test_main_response_format_can_force_legacy_mode():
    with patch("services.pipeline.config.LLM_OUTPUT_MODE", "legacy"):
        assert _main_response_format() is None


def test_main_response_format_can_use_json_schema_mode():
    with patch("services.pipeline.config.LLM_OUTPUT_MODE", "json_schema"):
        response_format = _main_response_format()

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "learning_agent_turn"
    assert "reply" in response_format["json_schema"]["schema"]["properties"]["action"]["enum"]


def test_structured_output_hint_maps_replies_to_action_envelope():
    prompt = _append_structured_output_hint("base", {"type": "json_object"})

    assert "Provider JSON Output Mode" in prompt
    assert '"action":"reply"' in prompt
    assert "Do not emit REPLY:" in prompt


def test_chat_response_blocks_machine_artifacts():
    raw = 'The user is answering.\n```json\n{"action":"assess","params":{}}\n```'

    payload = _response(raw)

    assert payload["message"] == CONTROLLED_FORMAT_FAILURE_MESSAGE


@pytest.mark.anyio
async def test_invalid_output_writes_private_failure_log(tmp_path):
    provider = FakeProvider(["<think>still invalid</think>"])

    with patch("services.pipeline.config.LLM_FAILURE_LOG_DIR", tmp_path):
        result = await _validate_or_retry_llm_output(
            provider=provider,
            raw="<think>bad raw</think>",
            original_text="model_validate?",
            system_prompt="system",
            session="learn_test",
            timeout=120,
        )

    assert result.startswith("REPLY: ⚠️")
    logs = sorted(tmp_path.glob("*.json"))
    assert len(logs) == 2
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in logs]
    assert {payload["stage"] for payload in payloads} == {"initial", "retry"}
    assert all(payload["original_text_snippet"] == "model_validate?" for payload in payloads)
