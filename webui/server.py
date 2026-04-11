#!/usr/bin/env python3
"""
Learning Agent — Database Web UI
A zero-dependency web interface for browsing and managing the knowledge DB.
Run:  python -m webui.server     (from learning_agent/)
  or: python webui/server.py     (from learning_agent/)
"""

import asyncio
import json
import mimetypes
import signal
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Add project root (learning_agent/) to path so we can import db
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))
import db  # noqa: E402
from services.state import PIPELINE_LOCK  # noqa: E402
from webui.chat_backend import (  # noqa: E402
    confirm_webui_action,
    decline_webui_action,
    handle_webui_message,
)

PORT = 8050
STATIC_DIR = Path(__file__).parent / "static"

# Page renderers (extracted to webui/pages.py and webui/helpers.py)
# Backward-compat re-exports (consumed by tests/test_action_log.py)
from webui.helpers import (  # noqa: E402,F401
    _esc,
    _relative_time,
    layout,  # noqa: E402 — used in Handler error path
)
from webui.pages import (  # noqa: E402
    page_404,
    page_actions,
    page_chat,
    page_concept_detail,
    page_concepts,
    page_dashboard,
    page_forecast,
    page_graph,
    page_reviews,
    page_topic_detail,
    page_topics,
)

# ============================================================================
# HTTP Handler
# ============================================================================

MIME_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

class InvalidJsonBodyError(ValueError):
    """Raised when a chat endpoint receives malformed JSON."""


def _run_chat_request(coro):
    """Run a chat coroutine under the current serialization guard."""
    with PIPELINE_LOCK:
        return asyncio.run(coro)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # Static file serving
        if path.startswith("/static/"):
            self._serve_static(path[8:])  # strip /static/
            return

        try:
            if path == "/":
                html = page_dashboard()
            elif path == "/topics":
                html = page_topics()
            elif path.startswith("/topic/"):
                tid = int(path.split("/")[2])
                html = page_topic_detail(tid)
            elif path == "/concepts":
                html = page_concepts()
            elif path == "/chat":
                html = page_chat()
            elif path == "/graph":
                html = page_graph()
            elif path.startswith("/concept/"):
                cid = int(path.split("/")[2])
                html = page_concept_detail(cid)
            elif path == "/reviews":
                html = page_reviews()
            elif path == "/actions":
                html = page_actions(parsed.query or "")
            elif path == "/forecast":
                html = page_forecast()
            elif path == "/api/forecast":
                qs = urllib.parse.parse_qs(parsed.query or "")
                range_type = qs.get("range", ["weeks"])[0]
                try:
                    data = db.get_due_forecast(range_type)
                    self._json_response(data)
                except ValueError as e:
                    self._json_response({"error": str(e)}, status=400)
                return
            elif path == "/api/forecast/concepts":
                qs = urllib.parse.parse_qs(parsed.query or "")
                range_type = qs.get("range", ["weeks"])[0]
                bucket_key = qs.get("bucket", ["0"])[0]
                try:
                    concepts = db.get_forecast_bucket_concepts(range_type, bucket_key)
                    self._json_response(concepts)
                except ValueError as e:
                    self._json_response({"error": str(e)}, status=400)
                return
            elif path == "/api/stats":
                self._json_response(db.get_review_stats())
                return
            elif path == "/api/topics":
                self._json_response(db.get_topic_map())
                return
            elif path == "/api/due":
                self._json_response(db.get_due_concepts())
                return
            elif path == "/api/actions":
                # Parse query params for filtering
                qs = urllib.parse.parse_qs(parsed.query or "")
                limit = min(200, int(qs.get("limit", [50])[0]))
                offset = int(qs.get("offset", [0])[0])
                action_f = qs.get("action", [None])[0] or None
                source_f = qs.get("source", [None])[0] or None
                entries = db.get_action_log(
                    limit=limit,
                    offset=offset,
                    action_filter=action_f,
                    source_filter=source_f,
                )
                self._json_response(
                    {
                        "entries": entries,
                        "total": db.get_action_log_count(
                            action_filter=action_f, source_filter=source_f
                        ),
                    }
                )
                return
            else:
                html = page_404()

            self._html_response(html)

        except Exception as e:
            self._html_response(
                layout(
                    "Error",
                    f'<div class="flash error">Error: {e}</div><p><a href="/">Go home</a></p>',
                ),
                status=500,
            )

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # CSRF: require custom header (browsers won't send cross-origin without CORS preflight)
        if self.headers.get("X-Requested-With") != "fetch":
            self._json_response({"ok": False, "error": "Forbidden"}, status=403)
            return

        try:
            if path == "/api/chat":
                payload = self._read_json_body()
                message = payload.get("message", "")
                if not isinstance(message, str):
                    raise ValueError("Field 'message' must be a string")
                data = _run_chat_request(handle_webui_message(message))
                self._json_response(data)
                return
            if path == "/api/chat/confirm":
                payload = self._read_json_body()
                data = _run_chat_request(confirm_webui_action(payload.get("action_data", {})))
                self._json_response(data)
                return
            if path == "/api/chat/decline":
                payload = self._read_json_body()
                data = _run_chat_request(decline_webui_action(payload.get("action_data", {})))
                self._json_response(data)
                return

            # DELETE concept: POST /api/concept/<id>/delete
            parts = path.split("/")
            if (
                len(parts) == 5
                and parts[1] == "api"
                and parts[2] == "concept"
                and parts[4] == "delete"
            ):
                try:
                    cid = int(parts[3])
                except ValueError:
                    self._json_response({"ok": False, "error": "Invalid concept ID"}, status=400)
                    return
                deleted = db.delete_concept(cid)
                if deleted:
                    self._json_response({"ok": True})
                else:
                    self._json_response({"ok": False, "error": "Concept not found"}, status=404)
                return

            self._json_response({"ok": False, "error": "Not found"}, status=404)

        except InvalidJsonBodyError:
            return
        except ValueError as e:
            if path.startswith("/api/chat"):
                self._json_response(
                    {"type": "error", "message": str(e), "pending_action": None},
                    status=400,
                )
            else:
                self._json_response({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            if path.startswith("/api/chat"):
                self._json_response(
                    {"type": "error", "message": str(e), "pending_action": None},
                    status=500,
                )
            else:
                self._json_response({"ok": False, "error": str(e)}, status=500)

    def _serve_static(self, rel_path: str):
        """Serve a file from the static/ directory."""
        # Prevent path traversal
        safe_path = Path(rel_path).name  # only the filename, no subdirs
        file_path = STATIC_DIR / safe_path
        if not file_path.is_file():
            self.send_error(404, "Static file not found")
            return

        ext = file_path.suffix.lower()
        content_type = MIME_TYPES.get(
            ext, mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        )

        try:
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                f"{content_type}; charset=utf-8"
                if ext in (".css", ".js", ".json")
                else content_type,
            )
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_error(500, "Error reading static file")

    def _read_request_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            length = 0
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _read_json_body(self) -> dict:
        body = self._read_request_body()
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json_response(
                {"type": "error", "message": "Invalid JSON body.", "pending_action": None},
                status=400,
            )
            raise InvalidJsonBodyError("Invalid JSON body")

    def _html_response(self, html: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _json_response(self, data, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def log_message(self, format, *args):
        # Quieter logging
        pass


# ============================================================================
# Main
# ============================================================================


def main(skip_init: bool = False):
    if not skip_init:
        db.init_databases()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Learning Agent DB UI running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")

    # Fast shutdown on Windows: signal handler calls shutdown() from a thread
    # Only works when running in the main thread (not when bot spawns webui in a thread)
    if threading.current_thread() is threading.main_thread():

        def _signal_shutdown(sig, frame):
            print("\nShutting down...")
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, _signal_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _signal_shutdown)

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    main()
