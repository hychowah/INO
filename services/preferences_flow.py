"""Shared preference-edit workflow helpers."""

import logging
import re

import config
from services import context as ctx
from services.llm import get_provider

logger = logging.getLogger("preferences_flow")


def parse_preferences_fence(raw: str) -> str:
    """Extract the content from a ```preferences fenced block in the LLM response."""
    match = re.search(r"```preferences\s*\n(.*?)\n```", raw, re.DOTALL)
    if not match:
        raise ValueError("LLM did not produce a valid preferences block")

    content = match.group(1).strip()
    if not content:
        raise ValueError("LLM produced an empty preferences block")
    return content


async def call_preference_edit(user_text: str) -> tuple[str, str]:
    """Call the LLM to produce an edited version of preferences.md."""
    system_prompt = ctx._get_base_prompt("preference-edit")
    provider = get_provider()
    raw = await provider.send(
        user_text,
        system_prompt=system_prompt,
        timeout=config.COMMAND_TIMEOUT,
    )
    proposed_content = parse_preferences_fence(raw)
    fence_start = raw.find("```preferences")
    preview_text = raw[:fence_start].strip() if fence_start != -1 else "Preferences updated."
    return preview_text, proposed_content


async def execute_preference_update(content: str) -> str:
    """Write updated content to preferences.md and invalidate the prompt cache."""
    ctx.PREFERENCES_MD_PATH.write_text(content, encoding="utf-8")
    ctx.invalidate_prompt_cache()
    logger.info("preferences.md updated and prompt cache invalidated")
    return "Preferences updated."