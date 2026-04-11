(function () {
  const thread = document.getElementById("chat-thread");
  const pendingHost = document.getElementById("chat-pending");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendButton = document.getElementById("chat-send");
  const status = document.getElementById("chat-status");

  if (!thread || !pendingHost || !form || !input || !sendButton || !status) {
    return;
  }

  const STORAGE_KEY = "learning-agent-pending-action";
  const history = Array.isArray(window.__CHAT_HISTORY) ? window.__CHAT_HISTORY : [];
  let pendingAction = loadPendingAction();
  let requestInFlight = false;

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
  }

  function loadPendingAction() {
    try {
      const raw = window.sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function savePendingAction(action) {
    pendingAction = action;
    try {
      if (action) {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(action));
      } else {
        window.sessionStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Ignore sessionStorage failures in the browser.
    }
    renderPendingAction();
  }

  function setBusy(isBusy, message) {
    requestInFlight = isBusy;
    input.disabled = isBusy;
    sendButton.disabled = isBusy;
    sendButton.textContent = isBusy ? "Sending..." : "Send";
    status.textContent = message || "";
  }

  function formatMarker(content) {
    const match = /^\[(confirmed|declined):\s+(.+)\]$/.exec(content || "");
    if (!match) {
      return null;
    }
    const verb = match[1] === "confirmed" ? "Confirmed" : "Declined";
    return `${verb}: ${match[2]}`;
  }

  function escapeHtml(content) {
    return String(content || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatInline(content) {
    return escapeHtml(content)
      .replace(/\[concept:(\d+)\]/g, '<a class="chat-inline-link" href="/concept/$1">concept:$1</a>')
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function renderRichText(content) {
    const normalized = String(content || "").replace(/\r\n/g, "\n").trim();
    if (!normalized) {
      return "";
    }

    return normalized
      .split(/\n{2,}/)
      .map(function (block) {
        const lines = block.split("\n").filter(Boolean);
        if (!lines.length) {
          return "";
        }

        if (lines.every(function (line) { return /^[-*]\s+/.test(line); })) {
          return `<ul class="chat-list">${lines
            .map(function (line) { return `<li>${formatInline(line.replace(/^[-*]\s+/, ""))}</li>`; })
            .join("")}</ul>`;
        }

        if (lines.length === 1) {
          const headingMatch = /^(#{1,3})\s+(.+)$/.exec(lines[0]);
          if (headingMatch) {
            return `<p class="chat-heading chat-heading-${headingMatch[1].length}">${formatInline(headingMatch[2])}</p>`;
          }
        }

        return `<p>${lines.map(formatInline).join("<br>")}</p>`;
      })
      .join("");
  }

  function appendMessage(role, content, timestamp, options) {
    const variant = options && options.variant ? options.variant : "default";
    const empty = thread.querySelector(".chat-empty");
    if (empty) {
      empty.remove();
    }

    const item = document.createElement("div");
    item.className = `chat-message chat-message-${role === "user" ? "user" : "assistant"}`;
    if (variant === "error") {
      item.classList.add("chat-message-error");
    }

    const marker = formatMarker(content);
    if (marker) {
      item.classList.add("chat-message-action");
      content = marker;
    }

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    if (variant === "error") {
      bubble.classList.add("chat-bubble-error");
      bubble.setAttribute("role", "alert");
    }
    if (role === "assistant" && !marker) {
      bubble.innerHTML = renderRichText(content);
    } else {
      bubble.textContent = content || "";
    }
    item.appendChild(bubble);

    if (timestamp) {
      const meta = document.createElement("div");
      meta.className = "chat-meta";
      meta.textContent = timestamp;
      item.appendChild(meta);
    }

    thread.appendChild(item);
    thread.scrollTop = thread.scrollHeight;
  }

  function renderHistory() {
    thread.innerHTML = "";
    if (!history.length) {
      const empty = document.createElement("div");
      empty.className = "chat-empty";
      empty.textContent = "No chat history yet. Start the conversation below.";
      thread.appendChild(empty);
      return;
    }

    history.forEach((entry) => {
      appendMessage(entry.role, entry.content, entry.timestamp);
    });
    thread.scrollTop = thread.scrollHeight;
  }

  function extractFollowupMessage(message, prefix) {
    if (typeof message !== "string") {
      return "";
    }
    if (!prefix) {
      return message;
    }
    const normalizedPrefix = `${prefix}\n\n`;
    if (message.startsWith(normalizedPrefix)) {
      return message.slice(normalizedPrefix.length);
    }
    return message;
  }

  function confirmationMarker(action) {
    if (!action || !action.action) {
      return "[confirmed]";
    }
    if (action.action === "add_concept") {
      return "[confirmed: add concept]";
    }
    if (action.action === "suggest_topic") {
      const title = action.params && action.params.title ? action.params.title : "topic";
      return `[confirmed: add topic "${title}"]`;
    }
    if (action.action === "preference_update") {
      return "[confirmed: preference update]";
    }
    if (action.action === "maintenance_review") {
      return "[confirmed: maintenance changes]";
    }
    if (action.action === "taxonomy_review") {
      return "[confirmed: taxonomy changes]";
    }
    return `[confirmed: ${action.action}]`;
  }

  function declineMarker(action) {
    if (!action || !action.action) {
      return "[declined]";
    }
    if (action.action === "add_concept") {
      return "[declined: add concept]";
    }
    if (action.action === "suggest_topic") {
      const title = action.params && action.params.title ? action.params.title : "topic";
      return `[declined: add topic "${title}"]`;
    }
    if (action.action === "preference_update") {
      return "[declined: preference update]";
    }
    if (action.action === "maintenance_review") {
      return "[declined: maintenance changes]";
    }
    if (action.action === "taxonomy_review") {
      return "[declined: taxonomy changes]";
    }
    return `[declined: ${action.action}]`;
  }

  function renderPendingAction() {
    pendingHost.innerHTML = "";
    pendingHost.hidden = !pendingAction;
    if (!pendingAction) {
      return;
    }

    const card = document.createElement("div");
    card.className = "chat-pending-card";

    const title = document.createElement("div");
    title.className = "chat-pending-title";
    title.textContent = "Pending confirmation";
    card.appendChild(title);

    const summary = document.createElement("div");
    summary.className = "chat-pending-summary";
    summary.innerHTML = renderRichText(
      pendingAction.message || "Resolve the pending action before continuing."
    );
    card.appendChild(summary);

    const error = document.createElement("div");
    error.className = "chat-pending-error";
    error.hidden = true;
    card.appendChild(error);

    const actions = document.createElement("div");
    actions.className = "chat-pending-actions";

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "btn btn-primary";
    confirmButton.textContent = "Confirm";

    const declineButton = document.createElement("button");
    declineButton.type = "button";
    declineButton.className = "btn";
    declineButton.textContent = "Decline";

    confirmButton.addEventListener("click", function () {
      resolvePendingAction("/api/chat/confirm", confirmButton, declineButton);
    });
    declineButton.addEventListener("click", function () {
      resolvePendingAction("/api/chat/decline", confirmButton, declineButton);
    });

    actions.appendChild(confirmButton);
    actions.appendChild(declineButton);
    card.appendChild(actions);
    pendingHost.appendChild(card);
  }

  function showPendingError(message) {
    const error = pendingHost.querySelector(".chat-pending-error");
    if (!error) {
      return;
    }
    error.hidden = !message;
    error.textContent = message || "";
  }

  async function apiPost(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "fetch",
      },
      body: JSON.stringify(payload),
    });

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("Invalid server response.");
    }

    if (!response.ok) {
      throw new Error(data.detail || data.message || data.error || "Request failed.");
    }
    return data;
  }

  async function resolvePendingAction(path, confirmButton, declineButton) {
    if (!pendingAction || requestInFlight) {
      return;
    }

    confirmButton.disabled = true;
    declineButton.disabled = true;
    showPendingError("");
    setBusy(true, path.endsWith("confirm") ? "Confirming action..." : "Declining action...");

    try {
      const current = pendingAction;
      const response = await apiPost(path, { action_data: current });

      if (path.endsWith("confirm")) {
        appendMessage("user", confirmationMarker(current));
        appendMessage(
          "assistant",
          extractFollowupMessage(response.message, current.message),
          undefined,
          { variant: response.type === "error" ? "error" : "default" }
        );
      } else {
        appendMessage("user", declineMarker(current));
        appendMessage("assistant", response.message || "Declined.");
      }

      savePendingAction(null);
    } catch (error) {
      confirmButton.disabled = false;
      declineButton.disabled = false;
      showPendingError(error.message || "Could not resolve the pending action.");
    } finally {
      setBusy(false, "");
      input.focus();
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const message = input.value.trim();

    if (requestInFlight) {
      return;
    }
    if (pendingAction && !message.startsWith("/")) {
      status.textContent = "Resolve the pending action before sending a new message.";
      return;
    }
    if (!message) {
      return;
    }

    appendMessage("user", message);
    input.value = "";
    resizeInput();
    setBusy(true, "Waiting for the learning agent...");

    try {
      const response = await apiPost("/api/chat", { message });
      if (response.clear_history) {
        thread.innerHTML = "";
        savePendingAction(null);
      }
      appendMessage("assistant", response.message || "", undefined, {
        variant: response.type === "error" ? "error" : "default",
      });
      if (response.type === "pending_confirm" && response.pending_action) {
        savePendingAction(response.pending_action);
      } else {
        savePendingAction(null);
      }
    } catch (error) {
      appendMessage("assistant", error.message || "Chat request failed.", undefined, {
        variant: "error",
      });
    } finally {
      setBusy(false, "");
      input.focus();
    }
  });

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  input.addEventListener("input", resizeInput);

  resizeInput();
  renderHistory();
  renderPendingAction();
})();