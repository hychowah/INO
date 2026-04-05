"""
LLM provider abstraction layer.

Two backends:
  - KimiCliProvider: shells out to kimi-cli (existing behaviour)
  - OpenAICompatibleProvider: calls any OpenAI-compatible API
    (Grok / DeepSeek / OpenAI / local vLLM / etc.)

Provider is selected via config.LLM_PROVIDER and instantiated once
by get_provider().
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from typing import Protocol, runtime_checkable

import config

logger = logging.getLogger("llm")


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
# KimiCliProvider
# ============================================================================


class KimiCliProvider:
    """Wraps the kimi-cli binary (subprocess, stdin→stdout)."""

    def __init__(
        self,
        cli_path: str,
        agents_md_path: str | None = None,
        preferences_path: str | None = None,
        personas_dir: str | None = None,
    ):
        self._cli_path = cli_path
        self._agents_md_path = agents_md_path
        self._preferences_path = preferences_path
        self._personas_dir = personas_dir

    # ---- public interface --------------------------------------------------

    async def send(
        self,
        prompt: str,
        *,
        session: str | None = None,
        system_prompt: str | None = None,
        timeout: int = 120,
    ) -> str:
        """Build a kimi-cli command and pipe *prompt* via stdin.

        *system_prompt* is **ignored** — the kimi-cli prompt already
        references AGENTS.md / preferences.md / persona by file path
        (the CLI reads them from disk).
        """
        # Prepend file-path references when the provider knows the paths
        if self._agents_md_path and self._preferences_path:
            # Resolve active persona file path
            persona_line = ""
            if self._personas_dir:
                try:
                    from db.preferences import get_persona

                    persona_name = get_persona()
                    import os

                    persona_path = os.path.join(self._personas_dir, f"{persona_name}.md")
                    if os.path.exists(persona_path):
                        persona_line = f"2. {persona_path}\n"
                except Exception:
                    pass  # Fallback: no persona file reference

            if persona_line:
                header = (
                    "Follow the instructions in these files "
                    "(do NOT summarize or acknowledge them):\n"
                    f"1. {self._agents_md_path}\n"
                    f"{persona_line}"
                    f"3. {self._preferences_path}\n\n"
                )
            else:
                header = (
                    "Follow the instructions in these two files "
                    "(do NOT summarize or acknowledge them):\n"
                    f"1. {self._agents_md_path}\n"
                    f"2. {self._preferences_path}\n\n"
                )
            prompt = header + prompt

        flags = "--print --final-message-only --input-format text"
        if session:
            flags = f"--session {session} {flags}"

        raw = await self._run(flags, stdin_text=prompt, timeout=timeout)
        return raw

    def clear_session(self, session: str) -> None:
        """No-op — kimi-cli manages sessions on disk."""
        pass

    # ---- internals ---------------------------------------------------------

    async def _run(
        self,
        command: str,
        *,
        stdin_text: str | None = None,
        timeout: int = 120,
    ) -> str:
        cli = self._cli_path
        if " " in cli and not (cli.startswith('"') or cli.startswith("'")):
            cli = f'"{cli}"'

        full_command = f"{cli} {command}".strip()

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        kwargs: dict = dict(
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(config.BASE_DIR.parent),
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if stdin_text is not None:
            kwargs["input"] = stdin_text

        preview = command[:100].replace("\n", " ")
        logger.info(f"Running kimi: {preview!r} (timeout={timeout}s)")

        result = await asyncio.to_thread(subprocess.run, full_command, **kwargs)

        logger.debug(
            f"Kimi exit={result.returncode}, "
            f"stdout={len(result.stdout)} chars, "
            f"stderr={len(result.stderr)} chars"
        )

        if result.returncode != 0:
            filtered = _filter_stderr(result.stderr)
            if filtered:
                logger.warning(f"Kimi stderr: {filtered[:300]}")
            if not result.stdout.strip():
                raise LLMError(
                    f"kimi-cli exited {result.returncode}: {filtered[:200] or '(no stderr)'}",
                    retryable=True,
                )

        return result.stdout.strip() if result.stdout else ""


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
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise LLMError(
                "openai package not installed.  pip install 'openai>=1.0,<2.0'",
                retryable=False,
            )

        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
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
            return msgs

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
# Helpers
# ============================================================================


def _filter_stderr(stderr: str) -> str:
    """Filter out kimi's decorative box-drawing output from stderr."""
    if not stderr:
        return ""
    filtered = [
        line
        for line in stderr.strip().split("\n")
        if line.strip()
        and not line.startswith("┌")
        and not line.startswith("│")
        and not line.startswith("└")
        and "✓" not in line
        and "✗" not in line
    ]
    return "\n".join(filtered)


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

    provider_name = getattr(config, "LLM_PROVIDER", "kimi")

    if provider_name == "kimi":
        agents_path = str((config.BASE_DIR / "AGENTS.md").resolve())
        prefs_path = str(config.PREFERENCES_MD.resolve())
        personas_dir = str(config.PERSONAS_DIR.resolve())
        _provider_instance = KimiCliProvider(
            cli_path=config.KIMI_CLI_PATH,
            agents_md_path=agents_path,
            preferences_path=prefs_path,
            personas_dir=personas_dir,
        )
        logger.info("LLM provider: kimi-cli")

    elif provider_name == "openai_compat":
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
            f"Unknown LLM_PROVIDER: {provider_name!r}. Valid: 'kimi', 'openai_compat'.",
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
