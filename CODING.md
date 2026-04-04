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
python -m pytest tests/ -v
python scripts/test_similarity.py
python bot.py
```

If you see `No module named pytest` or any missing-import error, you forgot to activate the venv.

---

## Project Overview

A personal learning coach with spaced repetition. Two entry points talk to the same pipeline:

```
bot.py  (Discord)  ─┐
                     ├──→  services/pipeline.py  →  services/tools.py (+tools_assess.py)  →  db/
api.py  (FastAPI)   ─┘
```

The runtime LLM (DeepSeek/Grok/kimi) is the brain — it decides what to teach, when to quiz, and how to adapt. The code is a thin executor: parse LLM JSON → call DB → return result.

---

## Project Structure

```
ROOT
├── AGENTS.md              # Pointer file — references data/skills/ (DO NOT put instructions here)
├── config.py              # All settings, loads .env via python-dotenv
├── bot.py                 # Entry point: Discord bot
├── api.py                 # Entry point: FastAPI REST API
├── requirements.txt
│
├── data/
│   ├── skills/            # Modular LLM skill files (loaded conditionally per mode)
│   │   ├── core.md        # Role, philosophy, response format, universal actions, rules
│   │   ├── quiz.md        # Quiz/assess actions, scoring rubric, adaptive quiz evolution
│   │   ├── knowledge.md   # Topic/concept CRUD, casual Q&A, overlap detection
│   │   └── maintenance.md # Maintenance mode behavioral rules
│   ├── personas/          # Persona preset .md files (mentor, coach, buddy)
│   └── preferences.md     # Runtime LLM user preferences
│
├── services/              # All business logic
│   ├── pipeline.py        # Orchestration: LLM calls, skill loading, fetch loop, action execution
│   ├── tools.py           # Action executor: maps LLM verbs → DB calls
│   ├── tools_assess.py    # Quiz/assess action handlers extracted from tools.py
│   ├── context.py         # Prompt builder: dynamic context for LLM calls
│   ├── embeddings.py      # Embedding service: lazy-loaded sentence-transformers singleton
│   ├── parser.py          # LLM response parsing and output classification
│   ├── llm.py             # LLM provider abstraction (kimi-cli, OpenAI-compat)
│   ├── scheduler.py       # Background review/maintenance scheduler (Discord only)
│   ├── state.py           # Shared mutable state (avoids circular imports)
│   ├── dedup.py           # Duplicate concept detection sub-agent
│   ├── repair.py          # Malformed action repair sub-agent
│   └── kimi.py            # kimi-cli specific helpers
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
├── webui/                 # Web UI: DB browser + knowledge graph visualization
│   ├── server.py          # stdlib HTTP server, routing + Handler class
│   ├── helpers.py         # HTML helpers (score_bar, layout, _esc, etc.)
│   ├── pages.py           # Page renderers (page_dashboard, page_topic_detail, etc.)
│   └── static/            # CSS, JS (graph.js for D3 graph, concepts.js, tree.js)
├── docs/                  # Architecture, dev notes, plans (index.md for map)
│   ├── architecture.md
│   ├── DEVNOTES.md
│   ├── index.md
│   └── plans/             # Feature plans (mobile-conversion.md, concept-relations.md)
├── scripts/               # agent.py (maintenance CLI), utility scripts
│   ├── migrate_vectors.py # One-time bulk reindex of existing SQLite data into Qdrant
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

## How to Add a New API Endpoint

1. **`api.py`** — Add the route with `@app.get/post`, include `dependencies=[Depends(verify_token)]`
2. Call existing `db.*` functions directly (sync is fine — they're fast)
3. For anything needing the LLM, follow the `/api/chat` pattern (async, calls pipeline)

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
python -m pytest tests/ -v            # all tests
python -m pytest tests/test_llm.py -v # single file
```

**Vector store tests** (`tests/test_vectors.py`) are automatically skipped when `qdrant-client` is not installed — `pytest.importorskip("qdrant_client")` at module top.

**Normal tests skip vector init** via `conftest.py` patching `db.core._init_vector_store` — no model or Qdrant needed for the rest of the suite.

Some older test files (e.g. `test_dedup.py`) are still manual scripts
(`python tests/test_dedup.py`), but newer tests use proper pytest
classes, fixtures, and assertions.

---

## Key Files You Should NOT Edit Casually

| File | Risk | Why |
|------|------|-----|
| `data/skills/*.md` | **High** | Runtime LLM prompt skill files. Every word affects behavior. Test changes by chatting with the bot. See DEVNOTES §1 for past formatting bugs. **No tone/style directives here** — those go in persona files. Preserve `<!-- DO NOT REMOVE -->` comments. |
| `AGENTS.md` | **Low** | Pointer file only — references data/skills/. No instructions here. |
| `data/preferences.md` | **Medium** | User preferences injected into every LLM call. |
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
cp .env.example .env                 # Fill in your secrets
python api.py                        # Start API on :8080
python bot.py                        # Start Discord bot
```

Both entry points can run simultaneously — SQLite WAL mode handles concurrent access.

---

## Future Direction — Mobile App (React Native)

> **Status:** Not started. Current priority is reliable backend + prompt instructions.
> The plan is to eventually ship this as a React Native / Expo mobile app.
> All work below is about making the **backend app-ready** — no mobile code yet.

### Why This Matters Now

The web UI (`webui/server.py`) uses a stdlib HTTP server with direct `import db` calls — HTML is built in Python f-strings. This is fine as a localhost dashboard but **not reusable** as an app frontend. The FastAPI API (`api.py`) is the intended backend for any future client (mobile, desktop, or web SPA).

**Current goal:** Expand `api.py` to cover all CRUD operations so that:
1. Any future frontend (React Native, web SPA) has a complete REST API to consume
2. The web dashboard could optionally be migrated to use the API too (not required)
3. No business logic lives in transport-specific code (bot.py, webui/server.py)

### Architecture (current + future)

```
[Future] Mobile App  ──→  api.py (FastAPI :8080)  ──→  services/pipeline.py  ──→  db/
Discord Bot          ──→  bot.py                   ──→  services/pipeline.py  ──→  db/
Web Dashboard        ──→  webui/server.py           ──→  db/  (direct, read-only)
```

### Current API Coverage (api.py)

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/chat` | POST | Bearer | Send message to LLM agent |
| `/api/chat/confirm` | POST | Bearer | Confirm pending add_concept |
| `/api/topics` | GET | Bearer | Hierarchical topic map |
| `/api/topics/{id}` | GET | Bearer | Topic detail + concepts |
| `/api/concepts/{id}` | GET | Bearer | Concept detail + remarks + reviews |
| `/api/due` | GET | Bearer | Due concepts for review |
| `/api/stats` | GET | Bearer | Aggregate review stats |
| `/api/persona` | GET/POST | Bearer | Get/switch persona |
| `/api/graph` | GET | Bearer | Knowledge graph nodes + edges (filterable) |
| `/api/health` | GET | None | Health check |

### API Gaps (to fill before mobile development)

These endpoints don't exist yet. They should be added to `api.py` when the backend is stable enough to start mobile work. Listed here as a roadmap — **do not implement until backend + prompt are solid.**

**Concept CRUD:**
- `GET /api/concepts` — list/search/filter with pagination
- `POST /api/concepts` — create concept → `db.add_concept()`
- `PUT /api/concepts/{id}` — update → `db.update_concept()`
- `DELETE /api/concepts/{id}` — delete → `db.delete_concept()`
- `POST /api/concepts/{id}/remarks` — add remark → `db.add_remark()`

**Topic CRUD:**
- `POST /api/topics` — create → `db.add_topic()`
- `PUT /api/topics/{id}` — update → `db.update_topic()`
- `DELETE /api/topics/{id}` — delete → `db.delete_topic()`
- `POST /api/topics/link` — link parent→child → `db.link_topics()`
- `POST /api/topics/unlink` — unlink → `db.unlink_topics()`

**Relations:**
- `GET /api/concepts/{id}/relations` → `db.get_relations()`
- `POST /api/relations` — add → `db.add_relation()`
- `DELETE /api/relations` — remove → `db.remove_relation()`

**Reviews & logs:**
- `GET /api/reviews` — review log with pagination
- `GET /api/reviews/next` — pull-based review (replaces Discord DM push)
- `GET /api/actions` — audit log with filters

### Design Rules (for when endpoints are added)

1. **Add to `api.py` only** — the webui server stays as a separate localhost dashboard.
2. **Always `dependencies=[Depends(verify_token)]`** except health check.
3. **RESTful verbs** — GET reads, POST creates, PUT updates, DELETE deletes.
4. **JSON in/out** — Pydantic request models, dict responses.
5. **`set_action_source('api')`** on all mutating endpoints.
6. **Pagination:** `?page=1&per_page=20` → `{items, total, page, per_page}`.

### Mobile-Specific Concerns (future, not now)

- **Quiz flow:** The `/api/chat` conversational loop handles quizzes naturally — no special quiz endpoints needed. The LLM manages the ask→answer→assess→next cycle.
- **Push notifications:** Reviews are delivered via Discord DM today. Mobile will need pull-based (`/api/due`) short-term, push (Expo/FCM) long-term.
- **Auth:** Current Bearer token is fine for single-user. Multi-user would need JWT with `/api/auth/login`.
- **CORS:** Already configured (`allow_origins=["*"]`) — ready for mobile.
