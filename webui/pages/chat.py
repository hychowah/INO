"""Chat page."""

import json

import db
from webui.helpers import layout


def page_chat() -> str:
    history = db.get_chat_history(limit=30)
    history_json = json.dumps(history, default=str).replace("</", "<\\/")
    data_script = f"""<script>
window.__CHAT_HISTORY = {history_json};
window.__API_AVAILABLE = true;
</script>"""

    body = f"""
    {data_script}
    <div class="chat-page">
      <div class="chat-shell">
        <div class="chat-header">
          <h2>Chat</h2>
          <p class="chat-subtitle">Talk to the learning agent from the web UI.</p>
        </div>

        <div id="chat-thread" class="chat-thread" aria-live="polite"></div>

        <div class="chat-footer">
          <div id="chat-pending" class="chat-pending" hidden></div>

          <form id="chat-form" class="chat-composer">
            <textarea id="chat-input" class="chat-input" placeholder="Ask a question, request a quiz, or tell the agent what you want to learn..." rows="1" aria-label="Message the learning agent"></textarea>
            <div class="chat-composer-actions">
              <span id="chat-status" class="chat-status" role="status" aria-live="polite"></span>
              <button id="chat-send" class="btn btn-primary" type="submit">Send</button>
            </div>
          </form>
        </div>

        <noscript>
          <div class="flash error">JavaScript is required for chat interactions.</div>
        </noscript>
      </div>
    </div>
    """

    return layout(
        "Chat",
        body,
        active="chat",
      extra_scripts='<script src="/static/chat.js?v=2"></script>',
      body_class="chat-layout",
    )