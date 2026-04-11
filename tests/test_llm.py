"""
Tests for the LLM provider abstraction layer.

Covers:
  1. LLMError — retryable / non-retryable
  2. KimiCliProvider — instantiation, file-path injection
  3. OpenAICompatibleProvider — session management, token truncation
  4. Provider factory — config-based selection
  5. Live smoke test — optional, requires real API credentials (--live flag)
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
import services.llm as llm_module
from services.llm import (
    KimiCliProvider,
    LLMError,
    OpenAICompatibleProvider,
    get_provider,
)

# ============================================================================
# Helpers for OpenAICompatibleProvider tests
# ============================================================================


def _make_mock_client():
    """Fresh mock openai client + response per test (avoids cross-test leakage)."""
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "  REPLY: hello from API  "
    response.usage = MagicMock(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client, response


def _make_provider(mock_client, **kwargs):
    """Create an OpenAICompatibleProvider with mocked client."""
    defaults = dict(
        base_url="https://api.test.com/v1",
        api_key="test-key",
        model="test-model",
        max_history_tokens=1000,
    )
    defaults.update(kwargs)
    p = OpenAICompatibleProvider(**defaults)
    p._client = mock_client
    return p


# ============================================================================
# 1. LLMError
# ============================================================================


class TestLLMError:
    def test_retryable_true(self):
        e = LLMError("timeout", retryable=True)
        assert e.retryable is True
        assert str(e) == "timeout"

    def test_retryable_false(self):
        e = LLMError("bad key", retryable=False)
        assert e.retryable is False
        assert str(e) == "bad key"

    def test_is_exception(self):
        assert isinstance(LLMError("x"), Exception)


# ============================================================================
# 2. KimiCliProvider
# ============================================================================


class TestKimiCliProvider:
    def test_instantiation_with_paths(self):
        kp = KimiCliProvider(
            cli_path="kimi",
            agents_md_path="/fake/AGENTS.md",
            preferences_path="/fake/preferences.md",
        )
        assert kp._cli_path == "kimi"

    def test_clear_session_noop(self):
        kp = KimiCliProvider(cli_path="kimi")
        kp.clear_session("test_session")  # should not raise

    def test_file_path_injection(self):
        kp = KimiCliProvider(
            cli_path="kimi",
            agents_md_path="/fake/AGENTS.md",
            preferences_path="/fake/preferences.md",
        )
        captured = {}

        async def mock_run(self, command, *, stdin_text=None, timeout=120):
            captured["stdin"] = stdin_text
            captured["command"] = command
            return "REPLY: test response"

        async def _test():
            with patch.object(KimiCliProvider, "_run", mock_run):
                result = await kp.send(
                    "dynamic context here\n\nuser said: hello",
                    session="test_sess",
                    system_prompt="ignored system prompt",
                    timeout=60,
                )
            assert "Follow the instructions in these two files" in captured["stdin"]
            assert "/fake/AGENTS.md" in captured["stdin"]
            assert "/fake/preferences.md" in captured["stdin"]
            assert "dynamic context here" in captured["stdin"]
            assert "--session test_sess" in captured["command"]
            assert "--print" in captured["command"]
            assert "--final-message-only" in captured["command"]
            assert result == "REPLY: test response"

        asyncio.run(_test())

    def test_no_paths(self):
        kp_bare = KimiCliProvider(cli_path="kimi")
        captured = {}

        async def mock_run(self, command, *, stdin_text=None, timeout=120):
            captured["stdin"] = stdin_text
            return "fixed json"

        async def _test():
            with patch.object(KimiCliProvider, "_run", mock_run):
                result = await kp_bare.send("Fix this: {}", session=None, timeout=30)
            assert "Follow the instructions" not in captured["stdin"]
            assert captured["stdin"] == "Fix this: {}"
            assert result == "fixed json"

        asyncio.run(_test())


# ============================================================================
# 3. OpenAICompatibleProvider
# ============================================================================


class TestOpenAICompatibleProvider:
    def test_basic_send(self):
        mock_client, _ = _make_mock_client()

        async def _test():
            p = _make_provider(mock_client)
            result = await p.send(
                "hello", session=None, system_prompt="You are helpful.", timeout=60
            )
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "You are helpful."
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == "hello"
            assert call_args.kwargs["model"] == "test-model"
            assert result == "REPLY: hello from API"

        asyncio.run(_test())

    def test_session_continuity(self):
        mock_client, mock_response = _make_mock_client()

        async def _test():
            p = _make_provider(mock_client)
            await p.send("first message", session="sess1", system_prompt="system instructions")
            mock_response.choices[0].message.content = "second response"
            await p.send("second message", session="sess1", system_prompt="different system")
            msgs, _ = p._sessions["sess1"]
            assert len(msgs) == 5  # system, user1, assistant1, user2, assistant2
            assert msgs[0]["role"] == "system"
            assert msgs[0]["content"] == "system instructions"
            assert msgs[1]["role"] == "user"
            assert msgs[1]["content"] == "first message"
            assert msgs[2]["role"] == "assistant"
            assert msgs[3]["role"] == "user"
            assert msgs[3]["content"] == "second message"
            assert msgs[4]["role"] == "assistant"

        asyncio.run(_test())

    def test_session_isolation(self):
        mock_client, mock_response = _make_mock_client()
        mock_response.choices[0].message.content = "resp"

        async def _test():
            p = _make_provider(mock_client)
            await p.send("msg in A", session="sessA", system_prompt="sys")
            await p.send("msg in B", session="sessB", system_prompt="sys")
            assert "sessA" in p._sessions
            assert "sessB" in p._sessions
            sess_a_msgs, _ = p._sessions["sessA"]
            sess_b_msgs, _ = p._sessions["sessB"]
            assert len(sess_a_msgs) == 3
            assert len(sess_b_msgs) == 3

        asyncio.run(_test())

    def test_clear_session(self):
        mock_client, mock_response = _make_mock_client()
        mock_response.choices[0].message.content = "resp"

        async def _test():
            p = _make_provider(mock_client)
            await p.send("msg", session="to_clear", system_prompt="sys")
            assert "to_clear" in p._sessions
            p.clear_session("to_clear")
            assert "to_clear" not in p._sessions
            p.clear_session("nonexistent")  # should not raise

        asyncio.run(_test())

    def test_get_messages_returns_copy_for_existing_session(self):
        mock_client, _ = _make_mock_client()
        p = _make_provider(mock_client)
        p._sessions["sess1"] = ([{"role": "system", "content": "sys"}], 0.0)

        messages = p._get_messages("sess1", "ignored")
        messages.append({"role": "user", "content": "mutated"})

        stored, _ = p._sessions["sess1"]
        assert stored == [{"role": "system", "content": "sys"}]

    def test_no_session(self):
        mock_client, mock_response = _make_mock_client()
        mock_response.choices[0].message.content = "one-shot resp"

        async def _test():
            p = _make_provider(mock_client)
            await p.send("dedup prompt", session=None, system_prompt=None, timeout=120)
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "dedup prompt"
            assert len(p._sessions) == 0

        asyncio.run(_test())

    def test_token_truncation(self):
        mock_client, mock_response = _make_mock_client()
        mock_response.choices[0].message.content = "r"

        async def _test():
            p = _make_provider(mock_client, max_history_tokens=50)
            system = "A" * 40
            for _ in range(5):
                await p.send("B" * 80, session="trunc_test", system_prompt=system)
            msgs, _ = p._sessions["trunc_test"]
            assert msgs[0]["role"] == "system"
            assert msgs[0]["content"] == system
            total_est = sum(len(m["content"]) // 4 for m in msgs)
            assert total_est <= 50, f"Token estimate {total_est} exceeds budget 50"

        asyncio.run(_test())

    def test_temperature_passed(self):
        mock_client, mock_response = _make_mock_client()
        mock_response.choices[0].message.content = "resp"

        async def _test():
            p = _make_provider(mock_client, temperature=0.7)
            await p.send("test", session=None)
            call_args = mock_client.chat.completions.create.call_args
            assert call_args.kwargs.get("temperature") == 0.7

        asyncio.run(_test())

    def test_temperature_omitted_when_none(self):
        mock_client, mock_response = _make_mock_client()
        mock_response.choices[0].message.content = "resp"

        async def _test():
            p = _make_provider(mock_client, temperature=None)
            await p.send("test", session=None)
            call_args = mock_client.chat.completions.create.call_args
            assert "temperature" not in call_args.kwargs

        asyncio.run(_test())


# ============================================================================
# 4. Provider Factory
# ============================================================================


class TestProviderFactory:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        llm_module._provider_instance = None
        yield
        llm_module._provider_instance = None

    def test_kimi_provider(self):
        with patch.object(config, "LLM_PROVIDER", "kimi"):
            p = get_provider()
            assert isinstance(p, KimiCliProvider)

    def test_openai_compat_missing_config(self):
        with (
            patch.object(config, "LLM_PROVIDER", "openai_compat"),
            patch.object(config, "LLM_API_BASE_URL", None),
            patch.object(config, "LLM_API_KEY", None),
            patch.object(config, "LLM_MODEL", None),
        ):
            with pytest.raises(LLMError) as exc_info:
                get_provider()
            assert not exc_info.value.retryable

    def test_openai_compat_valid_config(self):
        with (
            patch.object(config, "LLM_PROVIDER", "openai_compat"),
            patch.object(config, "LLM_API_BASE_URL", "https://api.test.com/v1"),
            patch.object(config, "LLM_API_KEY", "test-key"),
            patch.object(config, "LLM_MODEL", "test-model"),
        ):
            p = get_provider()
            assert isinstance(p, OpenAICompatibleProvider)

    def test_unknown_provider(self):
        with patch.object(config, "LLM_PROVIDER", "invalid"):
            with pytest.raises(LLMError, match="Unknown"):
                get_provider()


# ============================================================================
# 5. Live Smoke Test (optional — pass --live to enable)
# ============================================================================


@pytest.mark.skipif("--live" not in sys.argv, reason="pass --live to enable")
class TestLiveSmoke:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        llm_module._provider_instance = None
        yield
        llm_module._provider_instance = None

    def test_one_shot(self):
        provider = get_provider()

        async def _test():
            resp = await provider.send(
                "Reply with exactly: TEST_OK",
                session=None,
                system_prompt="You are a test bot. Follow instructions exactly.",
                timeout=30,
            )
            assert "TEST_OK" in resp

        asyncio.run(_test())

    def test_session_continuity(self):
        provider = get_provider()

        async def _test():
            await provider.send(
                "Remember the secret word: BANANA",
                session="live_test_sess",
                system_prompt="You are a test bot. Remember what the user tells you.",
                timeout=30,
            )
            resp = await provider.send(
                "What was the secret word I told you?",
                session="live_test_sess",
                timeout=30,
            )
            assert "BANANA" in resp.upper()
            provider.clear_session("live_test_sess")

        asyncio.run(_test())
