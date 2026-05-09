from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services import preferences_flow


def test_parse_preferences_fence_extracts_content():
    raw = "Updated preferences.\n\n```preferences\n- Keep replies short.\n```"

    content = preferences_flow.parse_preferences_fence(raw)

    assert content == "- Keep replies short."


def test_parse_preferences_fence_rejects_missing_block():
    with pytest.raises(ValueError, match="valid preferences block"):
        preferences_flow.parse_preferences_fence("No fenced output here")


@pytest.mark.anyio
async def test_call_preference_edit_returns_preview_and_content():
    provider = SimpleNamespace(
        send=AsyncMock(
            return_value="Updated preferences.\n\n```preferences\n- Keep replies short.\n```"
        )
    )

    with (
        patch("services.preferences_flow.ctx._get_base_prompt", return_value="prompt") as prompt_mock,
        patch("services.preferences_flow.get_provider", return_value=provider),
    ):
        preview_text, proposed_content = await preferences_flow.call_preference_edit(
            "keep replies short"
        )

    prompt_mock.assert_called_once_with("preference-edit")
    provider.send.assert_awaited_once()
    assert preview_text == "Updated preferences."
    assert proposed_content == "- Keep replies short."


@pytest.mark.anyio
async def test_execute_preference_update_writes_and_invalidates_cache(tmp_path: Path):
    preferences_path = tmp_path / "preferences.md"

    with (
        patch("services.preferences_flow.ctx.PREFERENCES_MD_PATH", preferences_path),
        patch("services.preferences_flow.ctx.invalidate_prompt_cache") as invalidate_mock,
    ):
        result = await preferences_flow.execute_preference_update("- Keep replies short.")

    assert preferences_path.read_text(encoding="utf-8") == "- Keep replies short."
    invalidate_mock.assert_called_once_with()
    assert result == "Preferences updated."