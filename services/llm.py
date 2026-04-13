"""LLM provider abstraction layer for OpenAI-compatible chat completions."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol, runtime_checkable

import config

logger = logging.getLogger("llm")

# Pre-import the openai resource submodules at module load time.
# AsyncOpenAI.chat is a @cached_property: on first access it triggers a
# synchronous chain of ~20 importlib calls (openai.resources.chat →
# openai.resources.beta → openai.resources.beta.realtime → …).  If that
# first access happens inside the asyncio event loop (e.g. on the first
# /review command) it blocks the loop long enough to kill the Discord
# heartbeat.  Importing openai.resources.chat here cascades through the
# full chain at startup — before the event loop starts — so every
# subsequent .chat access is an instant sys.modules hit.
try:
    import openai.resources.chat  # noqa: F401 — triggers full lazy-import cascade
    from openai import AsyncOpenAI as _AsyncOpenAI

    _OPENAI_AVAILABLE = True
except ImportError:
    _AsyncOpenAI = None  # type: ignore[assignment,misc]
    _OPENAI_AVAILABLE = False


# ============================================================================
# Shared types
# ============================================================================


class LLMError(Exception):
    """Raised when the LLM call fails."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class LLMProvider(Protocol):
    """Structural protocol — any object with send() and clear_session() works."""

    async def send(
        self,
        prompt: str,
        *,
        session: str | None = None,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> str:
        """Send a prompt and return the assistant's response text.

        Contract:
          - If *session* is provided and already has messages,
            *system_prompt* is ignored (it was set on the first call).
          - Return value is the assistant's message text only.
        """
        ...

    def clear_session(self, session: str) -> None:
        """Drop all stored state for *session*."""
        ...


# ============================================================================
# OpenAI-compatible API provider
# ============================================================================


class OpenAICompatibleProvider:
    """Async adapter for any OpenAI-compatible chat-completions endpoint
    (Grok, DeepSeek, OpenAI, local vLLM, …)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float | None = None,
        max_history_tokens: int = 40_000,
        thinking: str | None = None,
    ):
        if not _OPENAI_AVAILABLE:
            raise LLMError(
                "openai package not installed.  pip install 'openai>=1.0,<2.0'",
                retryable=False,
            )

        self._client = _AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_history_tokens = max_history_tokens
        self._thinking = thinking  # "enabled", "disabled", or None

        # session_name → (messages list, last_used timestamp)
        self._sessions: dict[str, tuple[list[dict], float]] = {}

    # ---- public interface --------------------------------------------------

    async def send(
        self,
        prompt: str,
        *,
        session: str | None = None,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> str:
        messages = self._get_messages(session, system_prompt)
        messages.append({"role": "user", "content": prompt})

        self._truncate_history(messages)

        logger.info(
            f"OpenAI-compat call: model={self._model}, "
            f"msgs={len(messages)}, session={session or 'none'}"
        )

        try:
            kwargs: dict = dict(
                model=self._model,
                messages=messages,
                timeout=timeout,
            )
            if self._temperature is not None:
                kwargs["temperature"] = self._temperature
            if config.LLM_MAX_TOKENS:
                kwargs["max_tokens"] = config.LLM_MAX_TOKENS
            if self._thinking:
                kwargs["extra_body"] = {"thinking": {"type": self._thinking}}
            if response_format is not None:
                kwargs["response_format"] = response_format

            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            self._handle_api_error(exc)

        content = response.choices[0].message.content or ""

        # Log token usage
        if response.usage:
            logger.info(
                f"Tokens: {response.usage.prompt_tokens} in + "
                f"{response.usage.completion_tokens} out = "
                f"{response.usage.total_tokens} total"
            )

        # Persist to session history
        messages.append({"role": "assistant", "content": content})
        if session:
            self._sessions[session] = (messages, time.time())

        return content.strip()

    def clear_session(self, session: str) -> None:
        self._sessions.pop(session, None)

    # ---- internals ---------------------------------------------------------

    def _get_messages(
        self,
        session: str | None,
        system_prompt: str | None,
    ) -> list[dict]:
        """Return the message list for this session (creating if needed)."""
        if session and session in self._sessions:
            msgs, _ = self._sessions[session]
            return [dict(msg) for msg in msgs]

        msgs: list[dict] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        return msgs

    def _truncate_history(self, messages: list[dict]) -> None:
        """Drop oldest non-system messages when history exceeds the budget."""
        budget = self._max_history_tokens
        while self._estimate_tokens(messages) > budget and len(messages) > 2:
            # Find the first non-system message to drop
            for i, m in enumerate(messages):
                if m["role"] != "system":
                    messages.pop(i)
                    break
            else:
                break  # only system left

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        return sum(len(m.get("content", "")) // 4 for m in messages)

    def _handle_api_error(self, exc: Exception) -> None:
        """Classify the exception and raise LLMError."""
        exc_name = type(exc).__name__

        try:
            from openai import APIConnectionError, AuthenticationError, RateLimitError
        except ImportError:
            raise LLMError(str(exc), retryable=True) from exc

        if isinstance(exc, AuthenticationError):
            raise LLMError(
                f"LLM auth failed — check LLM_API_KEY: {exc}",
                retryable=False,
            ) from exc

        if isinstance(exc, (RateLimitError, APIConnectionError)):
            raise LLMError(
                f"LLM transient error ({exc_name}): {exc}",
                retryable=True,
            ) from exc

        raise LLMError(
            f"LLM API error ({exc_name}): {exc}",
            retryable=True,
        ) from exc


# ============================================================================
# Provider factory (singleton)
# ============================================================================

_provider_instance: LLMProvider | None = None
_reasoning_provider_instance: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Return the configured LLM provider (created once, reused)."""
    global _provider_instance
    if _provider_instance is not None:
        return _provider_instance

    provider_name = getattr(config, "LLM_PROVIDER", "openai_compat")

    if provider_name == "openai_compat":
        base_url = getattr(config, "LLM_API_BASE_URL", None)
        api_key = getattr(config, "LLM_API_KEY", None)
        model = getattr(config, "LLM_MODEL", None)
        temperature = getattr(config, "LLM_TEMPERATURE", None)
        max_tokens = getattr(config, "LLM_MAX_HISTORY_TOKENS", 40_000)

        if not base_url or not api_key or not model:
            raise LLMError(
                "LLM_PROVIDER=openai_compat requires LLM_API_BASE_URL, "
                "LLM_API_KEY, and LLM_MODEL to be set in config / env.",
                retryable=False,
            )

        thinking = getattr(config, "LLM_THINKING", None)
        _provider_instance = OpenAICompatibleProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_history_tokens=max_tokens,
            thinking=thinking,
        )
        logger.info(f"LLM provider: openai_compat ({model} @ {base_url})")

    else:
        raise LLMError(
            f"Unknown LLM_PROVIDER: {provider_name!r}. Valid: 'openai_compat'.",
            retryable=False,
        )

    return _provider_instance


def get_reasoning_provider() -> LLMProvider:
    """Return the reasoning LLM provider for quiz question generation.

    Uses REASONING_LLM_* config if set, otherwise falls back to the
    main provider. Safe to call even when reasoning config is absent."""
    global _reasoning_provider_instance
    if _reasoning_provider_instance is not None:
        return _reasoning_provider_instance

    base_url = getattr(config, "REASONING_LLM_BASE_URL", None)
    api_key = getattr(config, "REASONING_LLM_API_KEY", None)
    model = getattr(config, "REASONING_LLM_MODEL", None)

    if not base_url or not api_key or not model:
        logger.info("Reasoning provider not configured — using main provider")
        _reasoning_provider_instance = get_provider()
        return _reasoning_provider_instance

    thinking = getattr(config, "REASONING_LLM_THINKING", None)
    _reasoning_provider_instance = OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        thinking=thinking,
    )
    logger.info(f"Reasoning provider: openai_compat ({model} @ {base_url})")
    return _reasoning_provider_instance
