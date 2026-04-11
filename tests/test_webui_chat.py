import json
import asyncio
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import db

import webui.server as webui_server
from webui.chat_backend import handle_webui_message
from webui.pages.chat import page_chat
from webui.server import Handler


def _make_handler(path: str, headers=None, body: bytes = b""):
    handler = object.__new__(Handler)
    handler.path = path

    handler.headers = headers or {}
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.status_code = None
    handler.sent_headers = []

    def send_response(code, message=None):
        handler.status_code = code

    def send_header(name, value):
        handler.sent_headers.append((name, value))

    def end_headers():
        return None

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    return handler


def test_page_chat_renders_with_bootstrap_history(test_db):
    db.add_chat_message("user", "hello from the browser")
    db.add_chat_message("assistant", "hello from the agent")

    html = page_chat()

    assert 'id="chat-thread"' in html
    assert 'window.__CHAT_HISTORY =' in html
    assert "hello from the browser" in html
    assert '/static/chat.js?v=2' in html
    assert 'class="container chat-layout"' in html
    assert 'aria-label="Message the learning agent"' in html
    assert 'role="status" aria-live="polite"' in html


def test_page_chat_escapes_script_terminators_in_bootstrap_history(test_db):
    db.add_chat_message("assistant", '</script><script>alert("x")</script>')

    html = page_chat()

    assert '</script><script>alert("x")</script>' not in html
    assert '<\\/script><script>alert(\\"x\\")<\\/script>' in html


def test_chat_post_requires_fetch_header(test_db):
    handler = _make_handler(
        "/api/chat",
        headers={"Content-Length": "19"},
        body=b'{"message": "hello"}',
    )

    Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 403
    assert payload == {"ok": False, "error": "Forbidden"}


def test_chat_post_dispatches_local_backend(test_db):
    body = b'{"message": "hello"}'
    handler = _make_handler(
        "/api/chat",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    seen = {}

    async def fake_handle(message):
        seen["message"] = message
        return {"type": "reply", "message": "Hello", "pending_action": None}

    with patch("webui.server.handle_webui_message", side_effect=fake_handle):
        Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 200
    assert seen == {"message": "hello"}
    assert payload == {"type": "reply", "message": "Hello", "pending_action": None}


def test_chat_post_invalid_json_body_returns_400(test_db):
    body = b'{not-json}'
    handler = _make_handler(
        "/api/chat",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 400
    assert payload == {
        "type": "error",
        "message": "Invalid JSON body.",
        "pending_action": None,
    }


def test_chat_post_rejects_non_string_message(test_db):
    body = b'{"message": {"nested": true}}'
    handler = _make_handler(
        "/api/chat",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 400
    assert payload == {
        "type": "error",
        "message": "Field 'message' must be a string",
        "pending_action": None,
    }


def test_chat_confirm_unknown_action_returns_400_chat_error_shape(test_db):
    body = b'{"action_data": {"action": "assess", "params": {"concept_id": 1}}}'
    handler = _make_handler(
        "/api/chat/confirm",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 400
    assert payload == {
        "type": "error",
        "message": "Action 'assess' cannot be confirmed in WebUI",
        "pending_action": None,
    }


def test_chat_confirm_add_topic_returns_400_chat_error_shape(test_db):
    body = b'{"action_data": {"action": "add_topic", "params": {"title": "Group"}}}'
    handler = _make_handler(
        "/api/chat/confirm",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 400
    assert payload == {
        "type": "error",
        "message": "Action 'add_topic' cannot be confirmed in WebUI",
        "pending_action": None,
    }


def test_chat_decline_unknown_action_returns_400_chat_error_shape(test_db):
    body = b'{"action_data": {"action": "assess", "params": {"concept_id": 1}}}'
    handler = _make_handler(
        "/api/chat/decline",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 400
    assert payload == {
        "type": "error",
        "message": "Action 'assess' cannot be declined in WebUI",
        "pending_action": None,
    }


def test_webui_main_registers_signal_handlers_in_main_thread(test_db):
    server = MagicMock()
    current = object()

    with (
        patch("webui.server.ThreadingHTTPServer", return_value=server),
        patch("webui.server.signal.signal") as mock_signal,
        patch("webui.server.threading.current_thread", return_value=current),
        patch("webui.server.threading.main_thread", return_value=current),
    ):
        webui_server.main(skip_init=True)

    server.serve_forever.assert_called_once_with(poll_interval=0.25)
    server.server_close.assert_called_once_with()
    assert mock_signal.call_count == 1 + int(hasattr(webui_server.signal, "SIGTERM"))
    assert mock_signal.call_args_list[0].args[0] == webui_server.signal.SIGINT


def test_webui_main_skips_signal_handlers_off_main_thread(test_db):
    server = MagicMock()

    with (
        patch("webui.server.ThreadingHTTPServer", return_value=server),
        patch("webui.server.signal.signal") as mock_signal,
        patch("webui.server.threading.current_thread", return_value=object()),
        patch("webui.server.threading.main_thread", return_value=object()),
    ):
        webui_server.main(skip_init=True)

    server.serve_forever.assert_called_once_with(poll_interval=0.25)
    server.server_close.assert_called_once_with()
    mock_signal.assert_not_called()


def test_handle_webui_message_ping_records_history(test_db):
    response = asyncio.run(handle_webui_message("/ping"))

    assert response == {"type": "reply", "message": "Pong!", "pending_action": None}
    history = db.get_chat_history(limit=5)
    assert history[-2]["content"] == "/ping"
    assert history[-1]["content"] == "Pong!"


def test_handle_webui_message_topics_uses_public_execute_action(test_db):
    with patch(
        "webui.chat_backend.execute_action",
        return_value=("reply", "**Your Knowledge Map:**\n\n- Control Systems"),
    ):
        response = asyncio.run(handle_webui_message("/topics"))

    assert response == {
        "type": "reply",
        "message": "Your Knowledge Map:\n\n- Control Systems",
        "pending_action": None,
    }
    history = db.get_chat_history(limit=5)
    assert history[-2]["content"] == "/topics"
    assert history[-1]["content"] == "Your Knowledge Map:\n\n- Control Systems"


def test_handle_webui_message_free_text_reply_records_history_once(test_db):
    with patch(
        "webui.chat_backend.pipeline.call_with_fetch_loop",
        new=AsyncMock(return_value="REPLY: Final answer"),
    ):
        response = asyncio.run(handle_webui_message("hello"))

    assert response == {
        "type": "reply",
        "message": "Final answer",
        "pending_action": None,
    }
    history = db.get_chat_history(limit=5)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Final answer"


def test_handle_webui_message_free_text_pending_confirm_records_exchange(test_db):
    action_data = {
        "action": "add_concept",
        "message": "Add this concept?",
        "params": {"title": "Rust", "topic_titles": ["Programming"]},
    }
    with (
        patch("webui.chat_backend.pipeline.call_with_fetch_loop", new=AsyncMock(return_value="ignored")),
        patch(
            "webui.chat_backend.parse_llm_response",
            return_value=("FETCH", "Add this concept?", action_data),
        ),
    ):
        response = asyncio.run(handle_webui_message("teach me rust"))

    assert response == {
        "type": "pending_confirm",
        "message": "Add this concept?",
        "pending_action": action_data,
    }
    history = db.get_chat_history(limit=5)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "teach me rust"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Add this concept?"


def test_handle_webui_message_clear_returns_clear_history_flag(test_db):
    db.add_chat_message("user", "old")
    db.add_chat_message("assistant", "history")

    response = asyncio.run(handle_webui_message("/clear"))

    assert response == {
        "type": "reply",
        "message": "Chat history cleared.",
        "pending_action": None,
        "clear_history": True,
    }
    assert db.get_chat_history(limit=5) == []


def test_handle_webui_review_command_works_without_api_server(test_db):
    cid = db.add_concept("Reviewable", "desc")
    with (
        patch("webui.chat_backend.pipeline.handle_review_check", return_value=[f"{cid}|review payload"]),
        patch("webui.chat_backend.pipeline.generate_quiz_question", new=AsyncMock(return_value={"concept_id": cid})),
        patch("webui.chat_backend.pipeline.package_quiz_for_discord", new=AsyncMock(return_value="FETCH: ignored")),
        patch("webui.chat_backend.pipeline.execute_llm_response", new=AsyncMock(return_value="REPLY: What is the key idea?")),
    ):
        response = asyncio.run(handle_webui_message("/review"))

    assert response == {
        "type": "reply",
        "message": "What is the key idea?",
        "pending_action": None,
    }
    assert db.get_session("active_concept_id") == str(cid)
    assert db.get_session("quiz_anchor_concept_id") == str(cid)
    assert db.get_session("last_quiz_question") == "What is the key idea?"


def test_handle_webui_review_command_does_not_duplicate_history(test_db):
    cid = db.add_concept("Reviewable", "desc")

    async def fake_execute_llm_response(_review_text, _llm_response, _mode):
        db.add_chat_message("user", f"[system: review quiz sent for concept #{cid} — awaiting response]")
        db.add_chat_message("assistant", "What is the key idea?")
        return "REPLY: What is the key idea?"

    with (
        patch("webui.chat_backend.pipeline.handle_review_check", return_value=[f"{cid}|review payload"]),
        patch("webui.chat_backend.pipeline.generate_quiz_question", new=AsyncMock(return_value={"concept_id": cid})),
        patch("webui.chat_backend.pipeline.package_quiz_for_discord", new=AsyncMock(return_value="FETCH: ignored")),
        patch("webui.chat_backend.pipeline.execute_llm_response", new=AsyncMock(side_effect=fake_execute_llm_response)),
    ):
        response = asyncio.run(handle_webui_message("/review"))

    assert response == {
        "type": "reply",
        "message": "What is the key idea?",
        "pending_action": None,
    }
    history = db.get_chat_history(limit=10)
    assert len(history) == 2
    assert history[0]["content"] == f"[system: review quiz sent for concept #{cid} — awaiting response]"
    assert history[1]["content"] == "What is the key idea?"


def test_handle_webui_preference_edit_returns_pending_confirm(test_db):
    with patch(
        "webui.chat_backend.pipeline.call_preference_edit",
        new=AsyncMock(return_value=("Short preview", "new preferences content")),
    ):
        response = asyncio.run(handle_webui_message("/preference make the tone more direct"))

    assert response["type"] == "pending_confirm"
    assert response["pending_action"]["action"] == "preference_update"
    assert response["pending_action"]["params"]["content"] == "new preferences content"


def test_chat_confirm_preference_update_records_history(test_db):
    body = json.dumps(
        {
            "action_data": {
                "action": "preference_update",
                "message": "Apply this preference change?",
                "params": {"content": "updated preference content"},
            }
        }
    ).encode("utf-8")
    handler = _make_handler(
        "/api/chat/confirm",
        headers={"X-Requested-With": "fetch", "Content-Length": str(len(body))},
        body=body,
    )

    with patch(
        "webui.chat_backend.pipeline.execute_preference_update",
        new=AsyncMock(return_value="Preferences updated."),
    ):
        Handler.do_POST(handler)

    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert handler.status_code == 200
    assert payload == {
        "type": "reply",
        "message": "Apply this preference change?\n\nPreferences updated.",
        "pending_action": None,
    }
    history = db.get_chat_history(limit=5)
    assert history[-2]["content"] == "[confirmed: preference update]"
    assert history[-1]["content"] == "Preferences updated."