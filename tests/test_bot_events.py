from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot import events as bot_events


@pytest.mark.anyio
async def test_on_ready_initializes_databases_before_scheduler_start(tmp_path):
    calls = []

    fake_tree = MagicMock()
    fake_tree.sync = AsyncMock(return_value=[])

    fake_loop = MagicMock()

    def _fake_create_task(coro):
        coro.close()
        return MagicMock()

    fake_loop.create_task.side_effect = _fake_create_task

    fake_bot = MagicMock()
    fake_bot.user = type("User", (), {"name": "Sleepy", "id": 123})()
    fake_bot.guilds = [object()]
    fake_bot.tree = fake_tree
    fake_bot.loop = fake_loop

    pref_md = tmp_path / "preferences.md"
    pref_template = tmp_path / "preferences.template.md"

    with (
        patch.object(bot_events, "bot", fake_bot),
        patch.object(bot_events.config, "PREFERENCES_MD", pref_md),
        patch.object(bot_events.config, "PREFERENCES_TEMPLATE_MD", pref_template),
        patch.object(bot_events.config, "AUTHORIZED_USER_ID", 999),
        patch.object(bot_events.config, "print_config"),
        patch.object(
            bot_events.pipeline,
            "init_databases",
            side_effect=lambda: calls.append("init"),
        ),
        patch.object(
            bot_events.scheduler,
            "start",
            side_effect=lambda *args, **kwargs: calls.append("start"),
        ),
    ):
        await bot_events.on_ready()

    assert calls[:2] == ["init", "start"]
    fake_tree.sync.assert_awaited_once()
