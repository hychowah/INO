# API Reference

This document describes all public API surfaces exposed by the Learning Agent: the Discord bot commands, the FastAPI REST backend, and the read-only Web UI.

---

## 1. Discord Bot (`bot.py` + `bot/` package)

The bot is the primary user-facing interface. All commands require the calling user to be listed in `LEARN_AUTHORIZED_USER_ID`.

### Commands

| Command | Description |
|---------|-------------|
| `/learn [text]` | Start or continue a learning session. Optionally pass a topic or question as `text`. |
| `/review` | Trigger a spaced-repetition quiz session. Concepts with 2+ prior reviews can show an `I know this` skip button for confident recall. |
| `/due` | Show concepts currently due for review. |
| `/topics` | Display your full knowledge map (topic hierarchy). |
| `/persona [name]` | Get or set the active persona (`mentor`, `coach`, `buddy`). Omit `name` to show current. |
| `/maintain` | Run the automated knowledge-base maintenance agent. |
| `/clear` | Clear the current channel's chat history. |
| `/ping` | Check that the bot is alive. |
| `/sync` | (Admin) Sync slash commands with Discord. |

### Message Handler

Any non-command message in an authorised channel is routed through `_handle_user_message()`, which invokes the full LLM pipeline:

```
on_message → _handle_user_message → services/pipeline.py → LLM → tools/actions → response
```

### Quiz UI Behavior

- Quiz questions can render Discord buttons in addition to the text reply.
- After an assessment, the bot shows navigation buttons such as `Quiz again`, `Next due`, and `Explain`.
- For concepts with `review_count >= 2`, eligible quiz questions can also show an `I know this` button that scores the review as confident recall without requiring a typed answer.
- The skip button is a Discord-only UI affordance. It is not a public REST action and is not emitted by the LLM.

### Authentication

Controlled by the `LEARN_AUTHORIZED_USER_ID` environment variable (a single Discord user ID). All commands include an `@authorized_only()` check.

---

## 2. FastAPI REST API (`api.py`)

The REST API shares the same pipeline as the Discord bot and is protected with a bearer token (`LEARN_API_SECRET_KEY`). All endpoints except `/api/health` require the header:

```
Authorization: Bearer <LEARN_API_SECRET_KEY>
```

Start the server:

```bash
python api.py
# or: uvicorn api:app --reload --host 0.0.0.0 --port 8080
```

Interactive docs are available at `http://localhost:8080/docs` (Swagger UI) and `http://localhost:8080/redoc`.

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Send a message through the full LLM pipeline. Returns a text reply and optional pending action. |
| `POST` | `/api/chat/confirm` | Confirm or reject a pending action returned by a previous `/api/chat` call. |

### Topics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/topics` | List all topics (tree structure). |
| `GET` | `/api/topics/{id}` | Get a single topic with its concepts. |
| `POST` | `/api/topics` | Create a new topic. |
| `PUT` | `/api/topics/{id}` | Update a topic name or parent. |
| `DELETE` | `/api/topics/{id}` | Delete a topic (`?force=true` to delete with concepts). |
| `POST` | `/api/topics/link` | Link two topics (parent → child). |
| `POST` | `/api/topics/unlink` | Remove a parent → child link. |

### Concepts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/concepts` | List concepts (filterable by `topic_id`, `search`, `limit`). |
| `GET` | `/api/concepts/{id}` | Get a single concept with remarks. |
| `POST` | `/api/concepts` | Create a new concept. |
| `PUT` | `/api/concepts/{id}` | Update a concept. |
| `DELETE` | `/api/concepts/{id}` | Delete a concept. |
| `POST` | `/api/concepts/{id}/remarks` | Append a remark to a concept. |
| `GET` | `/api/concepts/{id}/relations` | Get relations for a concept. |

### Relations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/relations` | Create a concept relation (`requires`, `related_to`, `part_of`). |
| `POST` | `/api/relations/remove` | Remove a concept relation. |

### Reviews & Stats

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/reviews` | List review history (filterable by `concept_id`, `limit`). |
| `GET` | `/api/reviews/next` | Get the next concept due for review. |
| `GET` | `/api/due` | Get concepts due for review (`?limit=10`). |
| `GET` | `/api/stats` | Aggregate knowledge-base statistics. |
| `GET` | `/api/actions` | Action log with optional filters (`user`, `type`, `since`, `limit`, `page`). |
| `GET` | `/api/graph` | Topic/concept graph data for visualisation (filterable by `topic_id`, `depth`). |

### Persona

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/persona` | Get the active persona name. |
| `POST` | `/api/persona` | Set the active persona (`mentor`, `coach`, `buddy`). |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Returns `{"status": "ok"}`. No auth required. |

---

## 3. Web UI (`webui/server.py`)

A read-only dashboard served on port `8050` (default) using Python's built-in HTTP server. No authentication is required (LAN/localhost use only by design).

Start with:

```bash
python webui/server.py
# or via the main API lifespan when WEBUI_ENABLED=true
```

### Pages

| Path | Description |
|------|-------------|
| `/` | Dashboard — summary stats and recently due concepts |
| `/topics` | Topic tree with mastery progress bars |
| `/topics/{id}` | Topic detail — concepts, scores, remarks |
| `/concepts` | Searchable concept list |
| `/concepts/{id}` | Concept detail — score history, remarks, relations |
| `/reviews` | Review history |
| `/actions` | Action log with filtering and time-range picker |
| `/graph` | Interactive D3.js force-directed knowledge graph |
| `/static/*` | Static assets (JS, CSS) |

The Web UI reads directly from the same SQLite databases used by the bot and API.

---

## 4. Authentication Summary

| Surface | Mechanism | Variable |
|---------|-----------|----------|
| Discord bot | Discord user ID allowlist | `LEARN_AUTHORIZED_USER_ID` |
| REST API | Bearer token header | `LEARN_API_SECRET_KEY` |
| Web UI | None (localhost-only by design) | — |

---

## 5. Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `LEARN_LLM_PROVIDER` | LLM backend (`kimi`, `openai`, `deepseek`, …) |
| `LEARN_LLM_MODEL` | Model name to use |
| `LEARN_LLM_API_KEY` | API key for the LLM provider |
| `LEARN_LLM_BASE_URL` | Base URL for the LLM API |
| `LEARN_BOT_TOKEN` | Discord bot token |
| `LEARN_AUTHORIZED_USER_ID` | Discord user ID allowed to use the bot |
| `LEARN_API_SECRET_KEY` | Bearer token for the REST API |
| `LEARN_DB_PATH` | Path to `knowledge.db` (default: `data/knowledge.db`) |
| `LEARN_CHAT_DB_PATH` | Path to `chat_history.db` (default: `data/chat_history.db`) |
