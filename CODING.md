# CODING.md — Development Instructions for AI Coding Assistants

> **Audience:** Copilot, Claude, Cursor, and human developers editing this codebase.
> **NOT for:** The runtime LLM — that reads `AGENTS.md` only.
>
> **Also read:** `docs/DEVNOTES.md` for bug history and architecture decisions before making changes.

---

## ⚠️ Always Use the venv

All commands (pytest, scripts, bot) **must** run inside the project's virtual environment. The system `python` does not have the required packages.

**AI agents: activate the venv BEFORE running any terminal command.** Do not use bare `python` or `python3` — always activate first.

```powershell
# Activate once per terminal session (PowerShell)
& .\venv\Scripts\Activate.ps1

# Then run commands normally
make test
make test-fast
python scripts/test_similarity.py
python bot.py
```

If you see `No module named pytest` or any missing-import error, you forgot to activate the venv.

**Frontend commands** (`npm run dev`, `npm run build`, `npm run test`) do **not** use the venv but do require **Node.js and npm** on your PATH. Run `npm install` inside `frontend/` once before using these commands.

---

## Project Overview

A personal learning coach with spaced repetition. Two Python entry points share the same backend pipeline; the React/TypeScript frontend is now the sole browser UI and talks to FastAPI over JSON and SSE:

```
bot.py  (Discord)  ─┬──┴────────────────────────────────────────────────────
api.py  (FastAPI)  ─┼───── services/pipeline.py ── services/tools.py (+tools_assess.py) ── db/
frontend/ (React)  ─┘  ← browser client, proxied to api.py in dev
```

The runtime LLM (Grok/DeepSeek/OpenAI-compatible providers) is the brain — it decides what to teach, when to quiz, and how to adapt. The code is a thin executor: parse LLM JSON → call DB → return result.

---

## Project Structure

```
ROOT
├── AGENTS.md              # Pointer file — references data/skills/ (DO NOT put instructions here)
├── config.py              # All settings, loads .env via python-dotenv
├── bot.py                 # Entry point: Discord bot
├── bot/                   # Discord bot package
│   ├── app.py             # Shared discord.py bot instance and client setup
│   ├── auth.py            # @authorized_only decorator for command gating
│   ├── commands.py        # Slash/hybrid command implementations
│   ├── events.py          # on_ready, on_message, and startup hooks
│   ├── handler.py         # Shared message handler that bridges into pipeline.py
│   └── messages.py        # Discord-safe message splitting and send helpers
├── api.py                 # Entry point: FastAPI REST API
├── api/                   # FastAPI package
│   ├── app.py             # App assembly and route registration
│   ├── auth.py            # Bearer-token verification dependency
│   ├── schemas.py         # Pydantic request/response models
│   └── routes/            # REST route modules (chat, topics, concepts, relations, misc, ...)
├── requirements.txt
│
├── data/
│   ├── skills/            # Modular LLM skill files (loaded conditionally per mode)
│   │   ├── core.md        # Role, philosophy, response format, universal actions, rules
│   │   ├── quiz.md        # Quiz/assess actions, scoring rubric, adaptive quiz evolution
│   │   ├── knowledge.md   # Topic/concept CRUD, casual Q&A, overlap detection
│   │   ├── maintenance.md # Maintenance mode behavioral rules
│   │   ├── taxonomy.md    # Taxonomy reorganization instructions (`/reorganize`, shared scheduler)
│   │   ├── preferences.md # Preference-edit instructions for `/preference` text mode
│   │   └── quiz_generator.md # P1 scheduled-quiz question generator instructions
│   ├── personas/          # Persona preset .md files (mentor, coach, buddy)
│   ├── preferences.template.md # Tracked default copied to runtime preferences.md on first bot startup
│   └── preferences.md     # Runtime LLM user preferences (local, git-ignored)
│
├── services/              # All business logic
│   ├── pipeline.py        # Orchestration: LLM calls, skill loading, fetch loop, action execution
│   ├── tools.py           # Action executor: maps LLM verbs → DB calls
│   ├── tools_assess.py    # Quiz/assess action handlers extracted from tools.py
│   ├── context.py         # Prompt builder: dynamic context for LLM calls
│   ├── embeddings.py      # Embedding service: lazy-loaded sentence-transformers singleton
│   ├── parser.py          # LLM response parsing and output classification
│   ├── llm.py             # LLM provider abstraction (OpenAI-compatible chat completions + reasoning provider)
│   ├── scheduler.py       # Background review scheduler + shared background jobs (bot or API host)
│   ├── backup.py          # Backup service: SQLite + vector store snapshots, retention pruning
│   ├── state.py           # Shared mutable state (avoids circular imports)
│   ├── formatting.py      # Discord message helpers: truncate_for_discord, truncate_with_suffix, format_quiz_metadata
│   ├── views.py           # Persistent Discord button views (maintenance, dedup, quiz, preference edit)
│   ├── dedup.py           # Duplicate concept detection sub-agent
│   ├── repair.py          # Malformed action repair sub-agent
│   └── chat_session.py    # Shared chat-session controller for FastAPI browser/API routes
│
├── db/                    # Database layer (SQLite)
│   ├── core.py            # Connections, init, datetime utils
│   ├── migrations.py      # Schema migration blocks (extracted from core.py)
│   ├── topics.py          # Topic CRUD, topic maps; vector sync hooks
│   ├── concepts.py        # Concept CRUD, search, detail views; vector sync hooks
│   ├── vectors.py         # Qdrant wrapper (upsert/delete/search, find_nearest, reindex_all)
│   ├── relations.py       # Concept↔concept relations
│   ├── reviews.py         # Review log, remarks
│   ├── chat.py            # Chat history, session state
│   ├── preferences.py     # Persona selection (get/set via session_state)
│   ├── diagnostics.py     # Maintenance diagnostics
│   ├── proposals.py       # Maintenance action proposals (user approval)
│   ├── action_log.py      # Action audit log
│   └── __init__.py        # Re-exports all public functions; VECTORS_AVAILABLE flag
│
├── tests/                 # pytest test suite
├── frontend/              # React/TypeScript/Vite SPA frontend (dev :5173, built served by FastAPI :8080)
│   ├── src/App.tsx        # Compatibility re-export for the main routed app shell
│   ├── src/App.test.tsx   # Frontend chat/integration-style unit tests (Vitest + Testing Library)
│   ├── src/routes.tsx     # SPA route ownership for Dashboard, Chat, Knowledge, Progress, compatibility routes, and detail views
│   ├── src/components/    # Shared shell components (AppShell/AppLayout) and local UI primitives
│   ├── src/pages/         # Route components and page-level tests
│   ├── src/types.ts       # Shared TypeScript types
│   ├── src/api.ts         # API fetch helpers, including chat SSE parsing
│   ├── e2e/               # Playwright browser smoke tests
│   ├── vite.config.ts     # Vite dev server config + proxy rules to localhost:8080
│   └── package.json       # npm scripts: dev, build, test, test:e2e
├── docs/                  # Architecture, dev notes, plans (index.md for map)
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DEVNOTES.md
│   ├── SETUP.md
│   ├── TAXONOMY_REBUILD.md
│   ├── index.md
│   └── plans/             # Feature design plans
├── scripts/               # agent.py (maintenance CLI), utility scripts
│   ├── dev_all.py         # Cross-platform dev launcher (API + Vite frontend + Discord bot)
│   ├── taxonomy_shadow_rebuild.py # Operator taxonomy preview/apply workflow
│   ├── migrate_vectors.py # One-time bulk reindex of existing SQLite data into Qdrant
│   ├── test_prompts.py    # Prompt-debugging harness for maintenance/reorganize/quiz modes
│   ├── test_quiz_generator.py # Manual test harness for the two-prompt scheduled-quiz pipeline
│   └── test_similarity.py # Configurable similarity test harness (tune thresholds)
└── .env                   # Secrets (git-ignored)
```

---

## Import Conventions

```python
# Config — always as module
import config                              # config.API_PORT, config.LLM_MODEL

# DB — always as package (submodule structure is invisible to consumers)
import db                                  # db.add_concept(...), db.get_topic(...)

# Services importing each other — use `from services import`
from services import context as ctx
from services import tools
from services.parser import parse_llm_response, process_output
from services.llm import get_provider, LLMError

# DB submodules importing core — direct submodule imports
from db.core import _conn, _now_iso, KNOWLEDGE_DB
```

**Rules:**
- Never `import services.pipeline` from another service — if you need something from pipeline, you're probably creating a circular dep. Use `services/state.py` for shared state.
- Never import `db.topics` directly outside the `db/` package — always go through `import db`.
- `services/__init__.py` is intentionally empty. Don't add re-exports.

---

## Async vs Sync

| Layer | Convention | Why |
|-------|-----------|-----|
| `db/` | **Sync** | Raw sqlite3, fast local I/O |
| `services/tools.py` | **Sync** | Pure DB calls, no I/O waits |
| `services/context.py` | **Sync** | File reads + DB queries |
| `services/pipeline.py` | **Async** (orchestration) | Awaits LLM provider |
| `services/llm.py` | **Async** (`send()`) | Network I/O to LLM |
| `services/dedup.py`, `repair.py` | **Async** | Call LLM provider |
| `services/backup.py` | **Sync** | File I/O + sqlite3 only |
| `bot.py`, `api.py`, `scheduler.py` | **Async** | Event loops |

**Rule of thumb:** If it calls the LLM → async. Everything else → sync.

---

## How to Test Vector Similarity

Before deploying and before tuning thresholds, run the interactive harness:
```powershell
& .\venv\Scripts\Activate.ps1                   # if not already active
python scripts/test_similarity.py              # all groups
python scripts/test_similarity.py --group steel  # one group
python scripts/test_similarity.py --list         # list groups
```
Add your own concept pairs at the bottom of `scripts/test_similarity.py` in the `TEST_SETS` list. Use the `"Title — description"` format (same as what the real system embeds).

Key thresholds (all in `config.py`, all overridable via env vars):
- `SIMILARITY_THRESHOLD_DEDUP` (0.92) — blocks near-duplicate `add_concept`
- `SIMILARITY_THRESHOLD_RELATION` (0.50) — minimum for relation candidate suggestions

---

## How to Add a New Action

1. **`services/tools.py`** (or `services/tools_assess.py` for quiz/assess handlers) — Write `_handle_<name>(params: dict) -> tuple[str, Any]`:
   - Return `('reply', result_string)` on success
   - Return `('error', error_string)` on failure
   - Return `('fetch', data_dict)` for fetch actions

2. **`services/tools.py`** — Register in `ACTION_HANDLERS` dict at bottom of file:
   ```python
   ACTION_HANDLERS = {
       ...
       'new_action': _handle_new_action,
   }
   ```

3. **`data/skills/*.md`** — Add documentation with a **concrete JSON example** (critical — the LLM will hallucinate the structure without one). Mark examples with `<!-- DO NOT REMOVE -->`. Put it in the appropriate skill file: quiz/assess actions go in `quiz.md`, CRUD actions in `knowledge.md`, etc.

4. **No changes needed** in `pipeline.py` — it dispatches via `tools.execute_action()` which reads `ACTION_HANDLERS`.

---

## Quiz State Guards

### `is_quiz_active()` — single source of truth

`services/pipeline.py::is_quiz_active()` is the **only** place that decides whether a quiz session is currently in progress. It checks the two session keys used today:

| Key | Set by | Cleared by |
|-----|--------|------------|
| `quiz_anchor_concept_id` | `_handle_quiz` | `_QUIZ_CLEARING_ACTIONS` after `assess` |
| `active_concept_ids` | `_handle_multi_quiz` | `_handle_multi_assess` at completion |

**If you add a new quiz type**, update `is_quiz_active()` to check its session key. Do **not** add a separate quiz-active check elsewhere — all callers depend on this one function.

### Guards belong in `execute_action`, not in action handlers

Actions that mutate scores (`assess`, `multi_assess`) are gated in `execute_action` (both `services/pipeline.py` and `scripts/agent.py`). The handler functions (`_handle_assess`, `_handle_multi_assess`) do **not** repeat this check.

**Rule:** If a new score-mutating action needs a prerequisite guard, add it in `execute_action` at the same level as the existing `assess`/`multi_assess` guard — not inside the handler. This keeps all bypass-prevention in one layer and leaves handlers as pure executors.

---

## How to Add a New API Endpoint

1. **`api/routes/<module>.py`** — Add the route on the appropriate router and include `dependencies=[Depends(verify_token)]` unless it is intentionally public like `/api/health`.
2. **`api/routes/__init__.py` / `api/app.py`** — Make sure the route module is registered if you add a new one.
3. Call existing `db.*` functions directly for DB-backed reads/writes (sync is fine — they are fast).
4. For anything needing the LLM or shared chat state, follow the `/api/chat` pattern (async, serialized through `services/state.py`, and routed through `services/chat_session.py` or `services/pipeline.py`).

---

## How to Add a New DB Function

1. Put it in the appropriate `db/*.py` submodule
2. Add it to the `db/__init__.py` re-exports
3. Call it as `db.new_function()` from anywhere
4. If it adds/updates/deletes a concept or topic, call `_vector_upsert()` or `_vector_delete()` after the SQL write (best-effort, wrapped in try/except)

---

## Connection Management

```python
from db.core import _conn

# Pattern 1: Manual (most common)
conn = _conn()
row = conn.execute("SELECT ...", (param,)).fetchone()
conn.close()
return dict(row) if row else None

# Pattern 2: Context manager (for transactions)
from db.core import _connection
with _connection() as conn:
    conn.execute("INSERT ...", (...))
    conn.execute("INSERT ...", (...))
    # auto-commits on success, rolls back on exception
```

- `_conn()` returns a connection with `row_factory=Row`, `foreign_keys=ON`, `journal_mode=WAL`
- Default DB is `KNOWLEDGE_DB`. Pass `CHAT_DB` for chat history.
- Connections are short-lived (open → use → close). No connection pool.

---

## Testing

Tests use **pytest**. **Activate the venv first** (see top of this file):
```powershell
& .\venv\Scripts\Activate.ps1              # if not already active
make test                             # full suite (parallel defaults from pyproject.toml)
make test-fast                        # unit-marked subset
python -m pytest tests/ -n 0          # single-threaded override for debugging
python -m pytest tests/test_llm.py -v # single file
```

For the React frontend tests (Vitest + Testing Library — no venv required):
```bash
make test-ui
# equivalent to: cd frontend && npm run test
```

**Vector store tests** (`tests/test_vectors.py`) are automatically skipped when `qdrant-client` is not installed — `pytest.importorskip("qdrant_client")` at module top.

**Normal tests skip vector init** via `conftest.py` patching `db.core._init_vector_store`, and they set `LEARN_DISABLE_VECTOR_SYNC=1` so CRUD helpers do not trigger embedding-model loads during ordinary test runs.

**Any test that reads or writes `session_state`** (via `db.get_session` / `db.set_session`) **must use the `test_db` fixture**. The reason: `db.chat` imports `CHAT_DB` by value at import time, so patching `db.core.CHAT_DB` alone is not sufficient. The `test_db` fixture patches `db.chat.CHAT_DB` directly. Without it, session writes in the test bleed into the real `chat_history.db`.

Some older test files (e.g. `test_dedup.py`) are still manual scripts
(`python tests/test_dedup.py`), but newer tests use proper pytest
classes, fixtures, and assertions.

---

## Key Files You Should NOT Edit Casually

| File | Risk | Why |
|------|------|-----|
| `data/skills/*.md` | **High** | Runtime LLM prompt skill files. Every word affects behavior. Test changes by chatting with the bot. See DEVNOTES §1 for past formatting bugs. **No tone/style directives here** — those go in persona files. Preserve `<!-- DO NOT REMOVE -->` comments. |
| `AGENTS.md` | **Low** | Pointer file only — references data/skills/. No instructions here. |
| `data/preferences.template.md` | **Medium** | Tracked default for user preferences. The runtime `data/preferences.md` copy is git-ignored and auto-created from this template on first startup. |
| `data/personas/*.md` | **Medium** | Persona presets. Changes reflected without restart (mtime cache). Token budget: ~600 tokens max per file. |
| `db/core.py` migrations | **High** | Schema migrations are append-only (in `db/migrations.py`). Never modify existing migration blocks. |
| `services/pipeline.py` | **Medium** | Central orchestrator. Changes here affect both Discord and API. |

---

## Code Style

- **Docstrings:** Triple-quoted, first line is short description. Reference DEVNOTES sections when relevant.
- **Section dividers:** `# ====...====` comment blocks between logical sections.
- **Type hints:** Use modern `str | None` syntax (Python 3.10+). Legacy code may use `Optional[str]`.
- **No classes in services** (except LLM providers) — module-level functions only.
- **Logging:** `logger = logging.getLogger("module_name")` at module level.
- **Path resolution:** `Path(__file__).parent.parent / "filename"` from services/ to find project root.
- **Config validation:** `validate_config()` returns error strings, not exceptions.

---

## How to Add a New Persona Preset

1. **Create `data/personas/<name>.md`** — follow the structure of existing presets (mentor.md, coach.md, buddy.md). Required sections:
   - Identity (archetype description)
   - Tone & Register
   - Humor policy
   - Feedback Style (behavioral rules, not just adjectives)
   - Emoji Policy
   - Quiz Interactions (example phrases for correct/wrong/next)
   - Anti-patterns

2. **Token budget:** Keep under ~600 tokens (~2500 chars). Run `python tests/test_persona.py` to verify.

3. **Guard comment:** Include `<!-- Controls TONE only. Does NOT override action formats... -->` at the top.

4. **No code changes needed** — the persona is auto-discovered from `data/personas/`. The `/persona` command and API endpoint will list it automatically.

5. **WARNING:** Never put tone/style directives in `AGENTS.md`. All personality goes in persona files. AGENTS.md is the behavioral rulebook; persona files are the voice.

6. **Hot-reload:** Persona file edits are reflected on the next LLM call without restart (mtime-based cache).

---

## Environment Setup

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt
cd frontend && npm install && cd ..  # install React frontend deps (requires Node.js)
cp .env.example .env                 # Fill in your secrets
```

Start services:

```bash
python api.py                        # FastAPI on :8080
python bot.py                        # Discord bot
cd frontend && npm run dev           # React dev server on :5173
```

Or start everything at once:

```bash
make dev-all                         # API + React dev server + Discord bot
```

All services can run simultaneously — SQLite WAL mode handles concurrent reads/writes.

---

## Future Direction — Mobile App (React Native)

> **Status:** React web SPA is live under `frontend/`. Mobile (React Native / Expo) is not started.
> Current priority is reliable backend + prompt instructions.

### Current Architecture

The React frontend (`frontend/`) is the primary web interface. FastAPI serves the built SPA on port 8080, and Vite serves the same SPA on port 5173 during development.

```
React Frontend       ──→  api.py (FastAPI :8080)  ──→  services/pipeline.py  ──→  db/
[Future] Mobile App  ──→  api.py (FastAPI :8080)  ──→  services/pipeline.py  ──→  db/
Discord Bot          ──→  bot.py                   ──→  services/pipeline.py  ──→  db/
```

### Current API Coverage (api.py)

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/chat` | POST | Bearer | Send message to the shared chat controller and get one final envelope |
| `/api/chat/stream` | POST | Bearer | SSE chat replay for the browser client |
| `/api/chat/bootstrap` | GET | Bearer | Load recent chat history and command chips |
| `/api/chat/confirm` | POST | Bearer | Confirm a chat-layer pending action |
| `/api/chat/decline` | POST | Bearer | Decline a chat-layer pending action |
| `/api/chat/action` | POST | Bearer | Execute structured browser chat actions |
| `/api/concepts` | GET | Bearer | Paginated concept list/search/filter |
| `/api/concepts` | POST | Bearer | Create a concept |
| `/api/topics` | GET | Bearer | Hierarchical topic map |
| `/api/topics/flat` | GET | Bearer | Flat topic list for selectors |
| `/api/topics/{id}` | GET | Bearer | Topic detail + concepts |
| `/api/topic-map` | GET | Bearer | Topic DAG with parent/child ids and counts |
| `/api/concepts/{id}` | GET | Bearer | Concept detail + remarks + reviews |
| `/api/concepts/{id}` | PUT/DELETE | Bearer | Update or delete a concept |
| `/api/concepts/{id}/remarks` | POST | Bearer | Add a concept remark |
| `/api/concepts/{id}/relations` | GET | Bearer | Read concept relations |
| `/api/topics` | POST | Bearer | Create a topic |
| `/api/topics/{id}` | PUT/DELETE | Bearer | Update or delete a topic |
| `/api/topics/link` | POST | Bearer | Link parent and child topics |
| `/api/topics/unlink` | POST | Bearer | Remove a topic link |
| `/api/relations` | POST | Bearer | Create a concept relation |
| `/api/relations/remove` | POST | Bearer | Remove a concept relation |
| `/api/reviews` | GET | Bearer | Review history |
| `/api/reviews/next` | GET | Bearer | Next due concept for review |
| `/api/due` | GET | Bearer | Due concepts for review |
| `/api/stats` | GET | Bearer | Aggregate review stats |
| `/api/action-summary` | GET | Bearer | Recent action counts for dashboard cards |
| `/api/actions` | GET | Bearer | Paginated action log with filters |
| `/api/actions/filters` | GET | Bearer | Distinct filter values for action log UIs |
| `/api/persona` | GET/POST | Bearer | Get/switch persona |
| `/api/forecast` | GET | Bearer | Forecast bucket summary |
| `/api/forecast/concepts` | GET | Bearer | Forecast bucket drill-down |
| `/api/graph` | GET | Bearer | Knowledge graph nodes + edges (filterable) |
| `/api/health` | GET | None | Health check |

### Remaining backend concerns before mobile development

The HTTP surface is already broad enough for an eventual mobile client. The main remaining concerns are operational and architectural rather than missing CRUD endpoints:

- move from the current single shared bearer token to per-user auth when multi-user support is activated
- expand CORS and deployment assumptions beyond localhost-only development
- decide whether mobile should use the buffered SSE chat path or a different chat transport
- keep browser-specific UI actions in `POST /api/chat/action` from turning into a generic RPC bucket without clear contracts

### Design Rules (for when endpoints are added)

1. **Add to FastAPI route modules only** — the browser surface is served through `api/routes/`.
2. **Always `dependencies=[Depends(verify_token)]`** except health check.
3. **RESTful verbs** — GET reads, POST creates, PUT updates, DELETE deletes.
4. **JSON in/out** — Pydantic request models, dict responses.
5. **`set_action_source('api')`** on all mutating endpoints.
6. **Pagination:** `?page=1&per_page=20` → `{items, total, page, per_page}`.

### Mobile-Specific Concerns (future, not now)

- **Quiz flow:** The `/api/chat` conversational loop handles quizzes naturally — no special quiz endpoints needed. The LLM manages the ask→answer→assess→next cycle.
- **Push notifications:** Reviews are delivered via Discord DM today. Mobile will need pull-based (`/api/due`) short-term, push (Expo/FCM) long-term.
- **Auth:** Current Bearer token is fine for single-user. Multi-user would need JWT with `/api/auth/login`.
- **CORS:** Currently limited to localhost origins in `api/app.py` (`localhost` / `127.0.0.1` on ports `8000` and `8080`). Expand that list before relying on mobile or remote clients.
