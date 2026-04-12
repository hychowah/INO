from unittest.mock import MagicMock, patch

import bot.events as bot_events


def test_start_webui_server_starts_daemon_thread():
    thread = MagicMock()

    with patch("bot.events.threading.Thread", return_value=thread) as mock_thread:
        result = bot_events._start_webui_server()

    assert result is thread
    mock_thread.assert_called_once_with(target=bot_events._run_webui_server, daemon=True)
    thread.start.assert_called_once_with()


def test_run_webui_server_uses_fastapi_app_and_webui_port():
    api_app = object()

    with (
        patch("bot.events.config.WEBUI_HOST", "127.0.0.1"),
        patch("bot.events.config.WEBUI_PORT", 8050),
        patch("bot.events._get_api_app", return_value=api_app),
        patch("bot.events.uvicorn.run") as mock_run,
    ):
        bot_events._run_webui_server()

    mock_run.assert_called_once_with(api_app, host="127.0.0.1", port=8050, log_level="info")