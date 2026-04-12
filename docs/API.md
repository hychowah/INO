# API Reference

This document describes the public API surfaces exposed by the Learning Agent: the Discord bot commands, the FastAPI REST backend, and the FastAPI-served browser routes used by the React frontend.

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

`api.py` is a thin wrapper that starts the FastAPI app from `api/app.py`, and route handlers live under `api/routes/`. The REST API shares the same pipeline as the Discord bot and is protected with a bearer token (`LEARN_API_SECRET_KEY`) for non-localhost callers. Requests that hit the local FastAPI port directly are allowed through the development localhost bypass. For remote or non-local callers, all endpoints except `/api/health` require the header:

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
| `POST` | `/api/chat` | Send a message through the full LLM pipeline. Returns one final `ChatResponse` envelope (`reply`, `error`, or `pending_confirm`). |
| `POST` | `/api/chat/stream` | SSE chat endpoint. Emits a `status` event first, then either a final `done` event containing the same envelope shape as `/api/chat` or an `error` event. |
| `POST` | `/api/chat/confirm` | Confirm a chat-layer pending action payload. In the normal conversational flow, `/api/chat` currently emits only intercepted `add_concept` and `suggest_topic` confirmations. |
| `POST` | `/api/chat/decline` | Decline a chat-layer pending action payload. In the normal conversational flow, `/api/chat` currently emits only intercepted `add_concept` and `suggest_topic` confirmations. |
| `POST` | `/api/chat/action` | Execute a structured UI action emitted by the chat frontend (button groups, proposal review items, multiple-choice actions). |

#### `POST /api/chat/confirm` — confirmable actions

Only a fixed chat-layer whitelist may be confirmed via this endpoint:

| Allowed action | Description |
|----------------|-------------|
| `add_concept` | Create a new concept |
| `suggest_topic` | Accept a suggested topic proposal |
| `preference_update` | Apply a proposed `preferences.md` update |
| `maintenance_review` | Apply maintenance changes from a review block |
| `taxonomy_review` | Apply taxonomy changes from a review block |

In the normal `/api/chat` flow, the API currently emits `pending_confirm` only for the intercepted actions `add_concept` and `suggest_topic`. The wider whitelist exists because the shared chat controller also supports confirming review-style chat payloads.

Any other action returns HTTP **400**:
```json
{"detail": "Action '<action>' cannot be confirmed via this endpoint"}
```

#### `POST /api/chat/decline`

Declines a whitelisted action payload. Uses the same `ConfirmRequest` schema and validates against the same chat-layer whitelist as `/confirm`.

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
| `GET` | `/api/concepts` | List concepts (filterable by `topic_id`, `search`, `status`, `page`, `per_page`, `sort`, `order`; `status` supports `all`, `due`, `upcoming`, and `never`; returns a paginated `items`/`total` envelope with normalized `latest_remark`, `topic_ids`, and `topics` fields). |
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
| `GET` | `/api/forecast` | Review forecast buckets used by the React forecast page. |
| `GET` | `/api/forecast/concepts` | Concept drill-down for one forecast bucket. |
| `GET` | `/api/graph` | Topic/concept graph data for visualisation (filterable by `topic_id`, `min_mastery`, `max_mastery`, `max_nodes`) used by the React graph page. |

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

## 3. FastAPI Page Routes

FastAPI serves the browser routes from `api/routes/pages.py`.

When `frontend/dist/index.html` exists, FastAPI serves the built React SPA entry for these routes:

| Path | Behavior |
|------|----------|
| `/` | Built SPA entry for the React dashboard; otherwise returns a minimal HTML response instructing the operator to run `make build-ui`. |
| `/chat` | Built SPA entry for the React chat client; otherwise returns the same missing-build HTML response. |
| `/topics` | Built SPA entry for the React topics list; otherwise returns the same missing-build HTML response. |
| `/topic/{topic_id}` | Built SPA entry for the React topic detail page; otherwise returns the same missing-build HTML response. |
| `/concepts` | Built SPA entry for the React concepts list; otherwise returns the same missing-build HTML response. |
| `/concept/{concept_id}` | Built SPA entry for the React concept detail page; otherwise returns the same missing-build HTML response. |
| `/graph` | Built SPA entry for the React graph page; otherwise returns the same missing-build HTML response. |
| `/reviews` | Built SPA entry for the React review-log page; otherwise returns the same missing-build HTML response. |
| `/forecast` | Built SPA entry for the React forecast page; otherwise returns the same missing-build HTML response. |
| `/actions` | Built SPA entry for the React activity log; otherwise returns the same missing-build HTML response. |

This SPA fallback is explicit, not catch-all: only the routes above serve `frontend/dist/index.html` when a build exists.

---

## 4. Chat Routes

The browser UI and other local clients now use the FastAPI routes below on port `8080`. They all delegate to the shared controller in `services/chat_session.py`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Standard JSON chat endpoint returning a single final envelope. |
| `POST` | `/api/chat/stream` | SSE chat endpoint that emits a `status` event followed by `done` or `error`. |
| `POST` | `/api/chat/confirm` | Confirm a pending action (`add_concept`, `suggest_topic`, `preference_update`, `maintenance_review`, `taxonomy_review`). |
| `POST` | `/api/chat/decline` | Decline a pending action. |
| `POST` | `/api/chat/action` | Execute a structured UI action payload. |
| `DELETE` | `/api/concepts/{id}` | Delete a concept via the browser concepts UI or other API clients. |

The browser UI reads from the same FastAPI process as the API and routes chat through the same in-process learning pipeline.

---

## 5. Authentication Summary

| Surface | Mechanism | Variable |
|---------|-----------|----------|
| Discord bot | Discord user ID allowlist | `LEARN_AUTHORIZED_USER_ID` |
| REST API | Bearer token header for non-local callers; localhost requests on `API_PORT` bypass the token check | `LEARN_API_SECRET_KEY` |
| FastAPI-served browser UI | Same FastAPI process and auth policy as the REST API; local browser requests on `API_PORT` use the localhost bypass | `LEARN_API_SECRET_KEY` |

Internally, db functions now accept an optional `user_id` and default to a ContextVar-backed lookup, but that is not yet activated at the Discord/API/browser entry points. From an operator perspective, the app still behaves as a single-user system.

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
