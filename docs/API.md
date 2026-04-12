# API Reference

This document describes all public API surfaces exposed by the Learning Agent: the Discord bot commands, the FastAPI REST backend, the transitional FastAPI page routes, and the local companion Web UI.

---

## 1. Discord Bot (`bot.py` + `bot/` package)

The bot is the primary user-facing interface. All interactive commands except `/ping` require the calling user to match `LEARN_AUTHORIZED_USER_ID`.

Current shipped behavior is still single-user at the interface layer. Internally, the database layer is now prepared for per-user scoping, but no entry point sets a non-default user identity yet, so all requests still resolve to the default user.

### Commands

| Command | Description |
|---------|-------------|
| `/learn [text]` | Start or continue a learning session. Optionally pass a topic or question as `text`. |
| `/review` | Trigger a spaced-repetition quiz session. Both manual `/review` calls and scheduler-triggered review DMs use the same skip-button eligibility rule (`review_count >= 2`). |
| `/due` | Show concepts currently due for review. |
| `/topics` | Display your full knowledge map (topic hierarchy). |
| `/persona [name]` | Get or set the active persona (`mentor`, `coach`, `buddy`). Omit `name` to show current. |
| `/maintain` | Run the automated knowledge-base maintenance agent. |
| `/reorganize` | Manually trigger the weekly taxonomy reorganization agent. |
| `/preference [text]` | Show the current runtime `preferences.md` when omitted, or propose an LLM-generated edit with Apply/Reject buttons when `text` describes a change. |
| `/backup` | Create an on-demand backup of all databases and the vector store. |
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
- After an assessment, the bot shows navigation buttons: `Quiz again`, `Next due`, `Explain`, and `Done`.
- The button emphasis adapts to the score: stronger answers promote `Next due`, while weaker answers promote `Explain`.
- For concepts with `review_count >= 2`, eligible quiz questions can also show an `I know this` button that scores the review as confident recall without requiring a typed answer.
- The skip button is a Discord-only UI affordance. It is not a public REST action and is not emitted by the LLM.

### Authentication

Controlled by the `LEARN_AUTHORIZED_USER_ID` environment variable (a single Discord user ID). All user-facing commands except `/ping` include an `@authorized_only()` check.

---

## 2. FastAPI REST API (`api.py`, `api/app.py`, `api/routes/`)

`api.py` is a thin wrapper that starts the FastAPI app from `api/app.py`, and route handlers live under `api/routes/`. The REST API shares the same pipeline as the Discord bot and is protected with a bearer token (`LEARN_API_SECRET_KEY`). All endpoints except `/api/health` require the header:

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
| `GET` | `/api/chat/bootstrap` | Bootstrap payload for the React chat frontend — returns recent chat history and available command chips. |
| `POST` | `/api/chat` | Send a message through the full LLM pipeline. Returns a text reply and optional `pending_confirm` for intercepted confirmation flows. |
| `POST` | `/api/chat/confirm` | Confirm a whitelisted action payload. In the normal conversational flow, `/api/chat` currently emits only intercepted confirmation actions. |
| `POST` | `/api/chat/decline` | Decline a whitelisted action payload. In the normal conversational flow, `/api/chat` currently emits only intercepted confirmation actions. |
| `POST` | `/api/chat/action` | Execute a structured UI action emitted by the chat frontend (button groups, proposal review items, multiple-choice actions). |

#### `POST /api/chat/confirm` — confirmable actions

Only a fixed whitelist of actions may be confirmed via this endpoint:

| Allowed action | Description |
|----------------|-------------|
| `add_concept` | Create a new concept |
| `suggest_topic` | Suggest a topic (no DB write) |
| `add_topic` | Create a new topic |
| `link_concept` | Link a concept to topic(s) |

In the normal `/api/chat` flow, the API only emits `pending_confirm` for the intercepted actions `add_concept` and `suggest_topic`. The broader whitelist exists so trusted callers can confirm compatible action payloads directly.

Any other action returns HTTP **400**:
```json
{"detail": "Action '<action>' cannot be confirmed via this endpoint"}
```

#### `POST /api/chat/decline`

Declines a whitelisted action payload. Uses the same `ConfirmRequest` schema and validates against the same `API_CONFIRMABLE_ACTIONS` whitelist as `/confirm`.

- Returns `{"type": "reply", "message": "Declined."}` on success.
- Returns HTTP **400** for any action type not in the whitelist.

### Topics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/topics/flat` | Flat topic list for dropdowns and lightweight filters. |
| `GET` | `/api/topic-map` | Flat topic DAG with `parent_ids`, `child_ids`, and per-topic counts used by the React dashboard and topic UIs. |
| `GET` | `/api/topics` | List all topics (tree structure). |
| `GET` | `/api/topics/{id}` | Get a single topic with its concepts. |
| `POST` | `/api/topics` | Create a new topic. |
| `PUT` | `/api/topics/{id}` | Update a topic name or parent. |
| `DELETE` | `/api/topics/{id}` | Delete a topic (`?force=true` to delete even when it still has concepts or child topics). |
| `POST` | `/api/topics/link` | Link two topics (parent → child). |
| `POST` | `/api/topics/unlink` | Remove a parent → child link. |

### Concepts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/concepts` | List concepts (filterable by `topic_id`, `search`, `page`, `per_page`, `sort`, `order`; returns a paginated `items`/`total` envelope with normalized `latest_remark`, `topic_ids`, and `topics` fields). |
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
| `GET` | `/api/reviews` | List review history. With `concept_id`, returns one concept's recent reviews; without it, returns the global recent review log. Supports `limit` from 1 to 200. |
| `GET` | `/api/reviews/next` | Get the next concept due for review. |
| `GET` | `/api/due` | Get concepts due for review (`?limit=10`). |
| `GET` | `/api/stats` | Aggregate knowledge-base statistics. |
| `GET` | `/api/action-summary` | Aggregated action counts for recent activity cards (`?days=7` by default). |
| `GET` | `/api/actions` | Action log with optional filters (`action`, `source`, `q` or `search`, `time`, `page`, `per_page`). |
| `GET` | `/api/actions/filters` | Distinct action and source values for building action-log filter UIs. |
| `GET` | `/api/forecast` | Review forecast buckets used by the legacy forecast page. |
| `GET` | `/api/forecast/concepts` | Concept drill-down for one forecast bucket. |
| `GET` | `/api/graph` | Topic/concept graph data for visualisation (filterable by `topic_id`, `min_mastery`, `max_mastery`, `max_nodes`). |

### Persona

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/persona` | Get the current persona and the full list of available presets. |
| `POST` | `/api/persona` | Set the active persona (`mentor`, `coach`, `buddy`). |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Returns `{"status": "ok"}`. No auth required. |

---

## 3. FastAPI Page Routes During Migration

FastAPI serves browser routes from `api/routes/pages.py` while the browser migration is in progress.

When `frontend/dist/index.html` exists, FastAPI serves the built React SPA entry for these routes:

| Path | Behavior |
|------|----------|
| `/` | Built SPA entry for the React dashboard; otherwise falls back to the legacy dashboard HTML page. |
| `/chat` | Built SPA entry for the React chat client; otherwise falls back to the legacy chat HTML page. |
| `/reviews` | Built SPA entry for the React review-log page; otherwise falls back to the legacy reviews HTML page. |

Other browser routes still render server-side HTML from `webui/pages/*` through FastAPI page handlers, including `/topics`, `/topic/{id}`, `/concepts`, `/concept/{id}`, `/forecast`, `/actions`, and `/graph`.

---

## 4. Bot Companion Web UI (`webui/server.py`)

A local-only dashboard served on port `8050` (default) using Python's built-in HTTP server. Started automatically when `bot.py` starts. No authentication required (LAN/localhost only).

> **Note:** The React SPA now owns `/`, `/chat`, and `/reviews` when served by FastAPI on port 8080. This companion Web UI on port 8050 remains the local-only legacy/operator surface.

### Pages

| Path | Description |
|------|-------------|
| `/` | Dashboard — summary stats and recently due concepts |
| `/topics` | Topic tree with mastery progress bars |
| `/topic/{id}` | Topic detail — concepts, scores, remarks |
| `/concepts` | Searchable concept list |
| `/concept/{id}` | Concept detail — score history, remarks, relations |
| `/reviews` | Review history |
| `/actions` | Action log with filtering and time-range picker |
| `/forecast` | Review forecast — due concepts bucketed by days / weeks / months |
| `/chat` | Legacy chat interface — local in-process LLM chat through the shared chat-session controller |
| `/api/actions?offset=&limit=&action=&source=` | JSON action log data for the Web UI filter controls |
| `/api/forecast?range=` | JSON forecast data — overdue count + 7 rolling buckets with counts and avg mastery |
| `/api/forecast/concepts?range=&bucket=` | JSON concept list for a specific bucket, sorted by mastery ASC |
| `/graph` | Interactive D3.js force-directed knowledge graph |
| `/static/*` | Static assets (JS, CSS) |

### Local Chat Routes (also available on FastAPI port 8080)

The routes below exist on **both** the companion Web UI (port 8050) and the FastAPI REST API (port 8080). Both surfaces delegate to the shared controller in `services/chat_session.py`; `webui/chat_backend.py` is retained as a compatibility import path for the legacy server and older tests.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | In-process Web UI chat endpoint backed by the shared chat-session controller. |
| `POST` | `/api/chat/confirm` | Confirm a Web UI pending action (`add_concept`, `suggest_topic`, `preference_update`, `maintenance_review`, `taxonomy_review`). |
| `POST` | `/api/chat/decline` | Decline a Web UI pending action. |
| `POST` | `/api/chat/action` | Execute a structured UI action payload. |
| `POST` | `/api/concept/{id}/delete` | Delete a concept from the concepts page. |

The Web UI reads directly from the same SQLite databases used by the bot and API for dashboard pages, and routes local chat through the same in-process learning pipeline.

---

## 5. Authentication Summary

| Surface | Mechanism | Variable |
|---------|-----------|----------|
| Discord bot | Discord user ID allowlist | `LEARN_AUTHORIZED_USER_ID` |
| REST API | Bearer token header | `LEARN_API_SECRET_KEY` |
| Web UI | None (localhost-only by design) | — |

Internally, db functions now accept an optional `user_id` and default to a ContextVar-backed lookup, but that is not yet activated at the Discord/API/Web UI entry points. From an operator perspective, the app still behaves as a single-user system.

---

## 6. Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `LEARN_LLM_PROVIDER` | LLM backend (`kimi` or `openai_compat`) |
| `LEARN_LLM_MODEL` | Model name for the OpenAI-compatible backend |
| `LEARN_LLM_API_KEY` | API key for the OpenAI-compatible backend |
| `LEARN_LLM_BASE_URL` | Base URL for the OpenAI-compatible backend |
| `LEARN_BOT_TOKEN` | Discord bot token |
| `LEARN_AUTHORIZED_USER_ID` | Discord user ID allowed to use the bot |
| `LEARN_API_SECRET_KEY` | Bearer token for the REST API |
| `LEARN_DB_PATH` | Path to `knowledge.db` (default: `data/knowledge.db`) |
| `LEARN_CHAT_DB_PATH` | Path to `chat_history.db` (default: `data/chat_history.db`) |
| `LEARN_SR_INTERVAL_EXPONENT` | Exponent for spaced-repetition interval formula (default: `0.075`); `interval_days = e^(score × exponent)` |
| `LEARN_BACKUP_DIR` | Directory for backup snapshots (default: `backups/` inside project root) |
| `LEARN_BACKUP_RETENTION_DAYS` | Number of days of backup snapshots to retain before pruning (default: `7`, minimum: `1`) |
| `LEARN_REASONING_LLM_*` | Optional reasoning-model settings for scheduled quiz question generation |
