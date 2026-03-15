"""
Test script for the LLM provider abstraction layer.

Tests:
  1. KimiCliProvider — instantiation, file-path injection
  2. OpenAICompatibleProvider — session management, token truncation
  3. Provider factory — config-based selection
  4. LLMError — retryable / non-retryable
  5. Live smoke test — optional, requires real API credentials

Usage:
  python tests/test_llm.py              # unit tests only (no API calls)
  python tests/test_llm.py --live       # include live API smoke test
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Ensure imports work from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from services.llm import (
    LLMError,
    KimiCliProvider,
    OpenAICompatibleProvider,
    get_provider,
    _provider_instance,
)
import services.llm as llm_module

PASS = 0
FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  ✓ {label}")


def fail(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  ✗ {label}  {detail}")


# ============================================================================
# 1. LLMError
# ============================================================================

print("\n=== 1. LLMError ===")

e1 = LLMError("timeout", retryable=True)
assert e1.retryable is True and str(e1) == "timeout"
ok("LLMError retryable=True")

e2 = LLMError("bad key", retryable=False)
assert e2.retryable is False and str(e2) == "bad key"
ok("LLMError retryable=False")

assert isinstance(e1, Exception)
ok("LLMError is an Exception")


# ============================================================================
# 2. KimiCliProvider
# ============================================================================

print("\n=== 2. KimiCliProvider ===")

kp = KimiCliProvider(
    cli_path="kimi",
    agents_md_path="/fake/AGENTS.md",
    preferences_path="/fake/preferences.md",
)
assert kp._cli_path == "kimi"
ok("Instantiation with paths")

# Test that clear_session is a no-op (shouldn't raise)
kp.clear_session("test_session")
ok("clear_session is no-op")


# Test file-path header injection
async def test_kimi_prompt_injection():
    """Verify KimiCliProvider prepends file-path refs to prompt."""
    captured = {}

    async def mock_run(self, command, *, stdin_text=None, timeout=120):
        captured["stdin"] = stdin_text
        captured["command"] = command
        return "REPLY: test response"

    with patch.object(KimiCliProvider, '_run', mock_run):
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
    ok("File-path refs prepended to prompt")

    assert "--session test_sess" in captured["command"]
    assert "--print" in captured["command"]
    assert "--final-message-only" in captured["command"]
    ok("Session and flags in command")

    assert result == "REPLY: test response"
    ok("Returns raw response string")

asyncio.run(test_kimi_prompt_injection())


# Test without paths (repair/dedup use case)
async def test_kimi_no_paths():
    kp_bare = KimiCliProvider(cli_path="kimi")
    captured = {}

    async def mock_run(self, command, *, stdin_text=None, timeout=120):
        captured["stdin"] = stdin_text
        return "fixed json"

    with patch.object(KimiCliProvider, '_run', mock_run):
        result = await kp_bare.send("Fix this: {}", session=None, timeout=30)

    assert "Follow the instructions" not in captured["stdin"]
    assert captured["stdin"] == "Fix this: {}"
    ok("No file-path refs when paths not set")

    assert result == "fixed json"
    ok("Returns raw string without paths")

asyncio.run(test_kimi_no_paths())


# ============================================================================
# 3. OpenAICompatibleProvider
# ============================================================================

print("\n=== 3. OpenAICompatibleProvider ===")

# Mock the openai import so we don't need a real API key
mock_client = MagicMock()
mock_response = MagicMock()
mock_response.choices = [MagicMock()]
mock_response.choices[0].message.content = "  REPLY: hello from API  "
mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=20, total_tokens=120)

mock_client.chat = MagicMock()
mock_client.chat.completions = MagicMock()
mock_client.chat.completions.create = AsyncMock(return_value=mock_response)


def make_test_provider(**kwargs):
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


# Basic send
async def test_api_basic_send():
    p = make_test_provider()
    mock_client.chat.completions.create.reset_mock()

    result = await p.send("hello", session=None, system_prompt="You are helpful.", timeout=60)

    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are helpful."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "hello"
    ok("System + user messages sent")

    assert call_args.kwargs["model"] == "test-model"
    ok("Model passed correctly")

    assert result == "REPLY: hello from API"
    ok("Response stripped and returned")

asyncio.run(test_api_basic_send())


# Session continuity
async def test_api_session_continuity():
    p = make_test_provider()
    mock_client.chat.completions.create.reset_mock()

    # First call — should include system prompt
    await p.send("first message", session="sess1", system_prompt="system instructions")

    # Second call — system_prompt should be ignored (already in session)
    mock_response.choices[0].message.content = "second response"
    await p.send("second message", session="sess1", system_prompt="different system")

    # After both calls complete, session has all messages including assistant replies
    msgs, _ = p._sessions["sess1"]
    # Should have: system, user1, assistant1, user2, assistant2
    assert len(msgs) == 5, f"Expected 5 messages in session, got {len(msgs)}"
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "system instructions"  # original, not "different system"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "first message"
    assert msgs[2]["role"] == "assistant"
    assert msgs[3]["role"] == "user"
    assert msgs[3]["content"] == "second message"
    assert msgs[4]["role"] == "assistant"
    ok("Session preserves history and ignores duplicate system_prompt")

asyncio.run(test_api_session_continuity())


# Session isolation
async def test_api_session_isolation():
    p = make_test_provider()
    mock_client.chat.completions.create.reset_mock()
    mock_response.choices[0].message.content = "resp"

    await p.send("msg in A", session="sessA", system_prompt="sys")
    await p.send("msg in B", session="sessB", system_prompt="sys")

    assert "sessA" in p._sessions
    assert "sessB" in p._sessions
    sess_a_msgs, _ = p._sessions["sessA"]
    sess_b_msgs, _ = p._sessions["sessB"]
    assert len(sess_a_msgs) == 3  # system + user + assistant
    assert len(sess_b_msgs) == 3
    ok("Sessions are isolated")

asyncio.run(test_api_session_isolation())


# clear_session
async def test_api_clear_session():
    p = make_test_provider()
    mock_response.choices[0].message.content = "resp"
    await p.send("msg", session="to_clear", system_prompt="sys")
    assert "to_clear" in p._sessions
    p.clear_session("to_clear")
    assert "to_clear" not in p._sessions
    ok("clear_session removes session")

    # Clear non-existent session — shouldn't raise
    p.clear_session("nonexistent")
    ok("clear_session on missing session is safe")

asyncio.run(test_api_clear_session())


# No session (one-shot, like dedup)
async def test_api_no_session():
    p = make_test_provider()
    mock_client.chat.completions.create.reset_mock()
    mock_response.choices[0].message.content = "one-shot resp"

    result = await p.send("dedup prompt", session=None, system_prompt=None, timeout=120)

    # The call should have been made with just a user message
    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs["messages"]
    # messages list is mutated after the call (assistant appended), so check roles
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "dedup prompt"
    ok("No-session call sends user message")
    assert len(p._sessions) == 0
    ok("No-session call doesn't persist history")

asyncio.run(test_api_no_session())


# Token truncation
async def test_api_token_truncation():
    p = make_test_provider(max_history_tokens=50)  # very low budget
    mock_response.choices[0].message.content = "r"

    # System prompt ~40 chars = ~10 tokens
    system = "A" * 40
    # Each user message ~80 chars = ~20 tokens
    for i in range(5):
        await p.send("B" * 80, session="trunc_test", system_prompt=system)

    msgs, _ = p._sessions["trunc_test"]
    # System message should always be preserved
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == system
    ok("System message preserved during truncation")

    total_est = sum(len(m["content"]) // 4 for m in msgs)
    assert total_est <= 50, f"Token estimate {total_est} exceeds budget 50"
    ok(f"History truncated to budget (est {total_est} tokens)")

asyncio.run(test_api_token_truncation())


# Temperature setting
async def test_api_temperature():
    p = make_test_provider(temperature=0.7)
    mock_client.chat.completions.create.reset_mock()
    mock_response.choices[0].message.content = "resp"

    await p.send("test", session=None)

    call_args = mock_client.chat.completions.create.call_args
    assert call_args.kwargs.get("temperature") == 0.7
    ok("Temperature passed to API")

    # Without temperature
    p2 = make_test_provider(temperature=None)
    mock_client.chat.completions.create.reset_mock()
    await p2.send("test", session=None)
    call_args2 = mock_client.chat.completions.create.call_args
    assert "temperature" not in call_args2.kwargs
    ok("Temperature omitted when None")

asyncio.run(test_api_temperature())


# ============================================================================
# 4. Provider Factory
# ============================================================================

print("\n=== 4. Provider Factory ===")

# Reset singleton
llm_module._provider_instance = None

# Default (kimi)
with patch.object(config, 'LLM_PROVIDER', 'kimi'):
    llm_module._provider_instance = None
    p = get_provider()
    assert isinstance(p, KimiCliProvider)
    ok("Factory returns KimiCliProvider for LLM_PROVIDER=kimi")

# openai_compat — missing config
llm_module._provider_instance = None
with patch.object(config, 'LLM_PROVIDER', 'openai_compat'), \
     patch.object(config, 'LLM_API_BASE_URL', None), \
     patch.object(config, 'LLM_API_KEY', None), \
     patch.object(config, 'LLM_MODEL', None):
    try:
        llm_module._provider_instance = None
        get_provider()
        fail("Factory should raise on missing openai_compat config")
    except LLMError as e:
        assert not e.retryable
        ok("Factory raises non-retryable LLMError on missing config")

# openai_compat — valid config
llm_module._provider_instance = None
with patch.object(config, 'LLM_PROVIDER', 'openai_compat'), \
     patch.object(config, 'LLM_API_BASE_URL', 'https://api.test.com/v1'), \
     patch.object(config, 'LLM_API_KEY', 'test-key'), \
     patch.object(config, 'LLM_MODEL', 'test-model'):
    llm_module._provider_instance = None
    p = get_provider()
    assert isinstance(p, OpenAICompatibleProvider)
    ok("Factory returns OpenAICompatibleProvider for openai_compat")

# Unknown provider
llm_module._provider_instance = None
with patch.object(config, 'LLM_PROVIDER', 'invalid'):
    try:
        llm_module._provider_instance = None
        get_provider()
        fail("Factory should raise on unknown provider")
    except LLMError as e:
        assert "Unknown" in str(e)
        ok("Factory raises on unknown provider")

# Reset singleton back to normal
llm_module._provider_instance = None


# ============================================================================
# 5. Live Smoke Test (optional, requires --live flag)
# ============================================================================

if "--live" in sys.argv:
    print("\n=== 5. Live Smoke Test ===")

    provider_name = getattr(config, 'LLM_PROVIDER', 'kimi')
    print(f"  Provider: {provider_name}")

    if provider_name == "openai_compat":
        print(f"  Model: {config.LLM_MODEL}")
        print(f"  Base URL: {config.LLM_API_BASE_URL}")

    llm_module._provider_instance = None
    provider = get_provider()

    async def live_test():
        # Simple one-shot
        print("\n  --- One-shot call ---")
        resp = await provider.send(
            "Reply with exactly: TEST_OK",
            session=None,
            system_prompt="You are a test bot. Follow instructions exactly.",
            timeout=30,
        )
        print(f"  Response: {resp[:200]}")
        if "TEST_OK" in resp:
            ok("Live one-shot response received")
        else:
            fail("Live one-shot — unexpected response", resp[:100])

        # Session continuity
        print("\n  --- Session continuity ---")
        await provider.send(
            "Remember the secret word: BANANA",
            session="live_test_sess",
            system_prompt="You are a test bot. Remember what the user tells you.",
            timeout=30,
        )
        resp2 = await provider.send(
            "What was the secret word I told you?",
            session="live_test_sess",
            timeout=30,
        )
        print(f"  Response: {resp2[:200]}")
        if "BANANA" in resp2.upper():
            ok("Live session continuity works")
        else:
            fail("Live session — didn't remember", resp2[:100])

        provider.clear_session("live_test_sess")

    asyncio.run(live_test())
else:
    print("\n  (Skipping live test — pass --live to enable)")


# ============================================================================
# Summary
# ============================================================================

print(f"\n{'='*50}")
print(f"  {PASS} passed, {FAIL} failed")
print(f"{'='*50}")
sys.exit(1 if FAIL else 0)
