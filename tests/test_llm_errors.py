"""Targeted tests for LLM error mapping and reasoning-provider selection."""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services import llm


@pytest.fixture(autouse=True)
def _reset_provider_singletons():
    llm._provider_instance = None
    llm._reasoning_provider_instance = None
    yield
    llm._provider_instance = None
    llm._reasoning_provider_instance = None


def _provider_without_init():
    return object.__new__(llm.OpenAICompatibleProvider)


class TestHandleApiError:
    def test_authentication_error_is_not_retryable(self, monkeypatch):
        fake_openai = SimpleNamespace(
            AuthenticationError=type("AuthenticationError", (Exception,), {}),
            APIConnectionError=type("APIConnectionError", (Exception,), {}),
            RateLimitError=type("RateLimitError", (Exception,), {}),
        )
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        with pytest.raises(llm.LLMError) as exc_info:
            _provider_without_init()._handle_api_error(fake_openai.AuthenticationError("bad key"))

        assert exc_info.value.retryable is False
        assert "LLM auth failed" in str(exc_info.value)

    @pytest.mark.parametrize(
        ("exc_name", "message"),
        [
            ("RateLimitError", "too many requests"),
            ("APIConnectionError", "network down"),
        ],
    )
    def test_transient_errors_are_retryable(self, monkeypatch, exc_name, message):
        fake_openai = SimpleNamespace(
            AuthenticationError=type("AuthenticationError", (Exception,), {}),
            APIConnectionError=type("APIConnectionError", (Exception,), {}),
            RateLimitError=type("RateLimitError", (Exception,), {}),
        )
        monkeypatch.setitem(sys.modules, "openai", fake_openai)
        exc_type = getattr(fake_openai, exc_name)

        with pytest.raises(llm.LLMError) as exc_info:
            _provider_without_init()._handle_api_error(exc_type(message))

        assert exc_info.value.retryable is True
        assert "LLM transient error" in str(exc_info.value)

    def test_other_errors_default_to_retryable(self, monkeypatch):
        fake_openai = SimpleNamespace(
            AuthenticationError=type("AuthenticationError", (Exception,), {}),
            APIConnectionError=type("APIConnectionError", (Exception,), {}),
            RateLimitError=type("RateLimitError", (Exception,), {}),
        )
        monkeypatch.setitem(sys.modules, "openai", fake_openai)

        with pytest.raises(llm.LLMError) as exc_info:
            _provider_without_init()._handle_api_error(RuntimeError("boom"))

        assert exc_info.value.retryable is True
        assert "LLM API error (RuntimeError): boom" in str(exc_info.value)


class TestReasoningProvider:
    def test_falls_back_to_main_provider_when_reasoning_not_configured(self):
        sentinel = object()

        with (
            patch.object(llm.config, "REASONING_LLM_BASE_URL", None),
            patch.object(llm.config, "REASONING_LLM_API_KEY", None),
            patch.object(llm.config, "REASONING_LLM_MODEL", None),
            patch("services.llm.get_provider", return_value=sentinel) as get_provider_mock,
        ):
            provider = llm.get_reasoning_provider()

        assert provider is sentinel
        get_provider_mock.assert_called_once_with()

    def test_uses_dedicated_reasoning_provider_when_configured(self):
        sentinel = object()

        with (
            patch.object(llm.config, "REASONING_LLM_BASE_URL", "https://reasoning.test/v1"),
            patch.object(llm.config, "REASONING_LLM_API_KEY", "reasoning-key"),
            patch.object(llm.config, "REASONING_LLM_MODEL", "reasoning-model"),
            patch.object(llm.config, "REASONING_LLM_THINKING", "enabled"),
            patch("services.llm.OpenAICompatibleProvider", return_value=sentinel) as provider_cls,
        ):
            provider = llm.get_reasoning_provider()

        assert provider is sentinel
        provider_cls.assert_called_once_with(
            base_url="https://reasoning.test/v1",
            api_key="reasoning-key",
            model="reasoning-model",
            thinking="enabled",
        )
