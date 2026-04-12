# Learning Agent

An LLM-first spaced repetition system where **all learning intelligence lives in the prompt, not in code**. The codebase provides thin CRUD plumbing and a pipeline that shuttles messages between user, LLM, and database — the LLM decides what to teach, when to quiz, and how to adapt.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Features

- **LLM-driven pedagogy** — Topic/concept extraction, quiz generation, and knowledge assessment are all handled by the LLM via a modular prompt system with hot-reloadable skill files
- **Score-based spaced repetition** — Asymmetric 0–100 scoring with exponential intervals (custom algorithm, not SM-2)
- **Quiz skip button** — After 2+ reviews, eligible quiz questions show an `I know this` button that scores confident recall without forcing a typed answer
- **Hybrid search** — Qdrant vector store (768-dim, `all-mpnet-base-v2`) + SQLite FTS5, with graceful degradation if Qdrant is unavailable
- **Multi-concept synthesis quizzes** — Semantically clusters related concepts for cross-topic questions
- **Self-improving remarks** — The LLM writes and reads its own persistent notes per concept, creating a feedback loop across sessions
- **Multiple interfaces** — Discord bot, FastAPI REST API, and the FastAPI-served React browser UI share the same learning pipeline and data stores
- **Knowledge graph** — DAG-based topic hierarchy with many-to-many concept mapping
- **Web dashboard + React SPA** — FastAPI serves the React browser UI for dashboard, chat, topics, concepts, graph, reviews, forecast, and activity routes
- **Automated maintenance** — Background agent for DB health triage, duplicate detection, and knowledge base cleanup
- **Automated data backup** — Scheduled weekly snapshot of both databases and the vector store into timestamped subdirectories; `/backup` slash command for on-demand backup with pruning of snapshots older than the configured retention window
- **Editable user preferences** — `/preference` shows or updates the runtime `preferences.md` file through an isolated LLM edit flow with explicit Apply/Reject confirmation
- **Configurable personas** — Buddy / Coach / Mentor presets loaded from Markdown files
- **Defense-in-depth** — Prompt rules + code guards + temptation reduction to prevent score inflation, phantom adds, and duplicates

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  User Interfaces                                                │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────────┐  │
│  │ Discord Bot │  │  REST API  │  │   Local Web UI           │  │
│  │  bot.py     │  │  api.py    │  │  FastAPI + React/HTML    │  │
│  └──────┬──────┘  └──────┬─────┘  └────────────┬─────────────┘  │
├─────────┼────────────────┼─────────────────────┼────────────────┤
│  Pipeline Layer          │                     │                │
│         ▼                ▼                     │                │
│  ┌─────────────────────────────┐               │                │
│  │  pipeline.py (orchestrator) │               │                │
│  │  context → LLM → parse →   │               │                │
│  │  execute (with fetch loop)  │               │                │
│  └──┬──────────┬───────────────┘               │                │
│     │          │                               │                │
│     ▼          ▼                               │                │
│  ┌─────────┐ ┌──────────┐                      │                │
│  │context  │ │ tools.py  │                      │                │
│  │  .py    │ │ (action   │                      │                │
│  │(prompt) │ │ executor) │                      │                │
│  └────┬────┘ └─────┬─────┘                      │                │
├───────┼────────────┼────────────────────────────┼────────────────┤
│  Data Layer        │                            │                │
│       ▼            ▼                            ▼                │
│  ┌──────────────────────────────────────────────────────┐       │
│  │                   db/ package                        │       │
│  │  core · topics · concepts · reviews · chat · vectors │       │
│  └──────┬───────────────────────┬───────────────────────┘       │
│         ▼                       ▼                    ▼           │
│  ┌──────────────┐  ┌───────────────────┐  ┌────────────────┐   │
│  │ knowledge.db  │  │  chat_history.db  │  │ Qdrant vectors │   │
│  │ (SQLite WAL)  │  │  (SQLite WAL)     │  │ (embedded)     │   │
│  └──────────────┘  └───────────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

The **fetch loop** is the key architectural pattern: the LLM can issue up to 3 invisible `fetch` actions per user turn to gather context (topic lists, concept details, review history) before composing its response. This keeps the LLM in control of what data it needs, without sending everything upfront.

Current runtime behavior is still single-user end-to-end: Discord access is gated by one `LEARN_AUTHORIZED_USER_ID`, the REST API uses one bearer token, and the Web UI is local-only. The DB layer now contains dormant per-user scaffolding (`user_id` columns, `users` table, ContextVar-based lookup), but entry points still resolve to the default user until that activation work is done.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture documentation with data flow diagrams, schema definitions, and module responsibilities.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Databases | SQLite (WAL mode) × 2 |
| Vector Store | Qdrant (embedded mode) |
| Embeddings | sentence-transformers (`all-mpnet-base-v2`, 768-dim) |
| LLM Backend | `kimi` CLI or any OpenAI-compatible API (Grok, DeepSeek, OpenAI, …) |
| Discord | discord.py |
| REST API | FastAPI + Uvicorn |
| Web UI | FastAPI-served React/TypeScript/Vite SPA + Tailwind CSS + local UI primitives |

> **Note:** `sentence-transformers` pulls in PyTorch (~2 GB download). For CPU-only installs:
> `pip install torch --index-url https://download.pytorch.org/whl/cpu` before installing requirements.

## Quick Start

```bash
# Clone and set up
git clone https://github.com/hychowah/INO.git
cd INO
python -m venv venv

# Activate virtual environment
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows (cmd)
.\venv\Scripts\Activate.ps1       # Windows (PowerShell)

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env              # Linux / macOS  (Windows: copy .env.example .env)
```

Edit `.env` with your LLM provider settings:

```dotenv
LEARN_LLM_PROVIDER=openai_compat
LEARN_LLM_BASE_URL=https://api.x.ai/v1    # or any OpenAI-compatible endpoint
LEARN_LLM_API_KEY=your_api_key_here
LEARN_LLM_MODEL=grok-3
LEARN_AUTHORIZED_USER_ID=your_discord_user_id
```

If you omit `LEARN_LLM_PROVIDER`, the app defaults to `kimi`. For the `kimi` CLI path, install and authenticate the `kimi` binary, then either omit the OpenAI-compatible block above or set `LEARN_LLM_PROVIDER=kimi` explicitly.

Then run:

```bash
python bot.py          # Discord bot
python api.py          # FastAPI app on http://localhost:8080
make build-ui          # Optional: rebuild the React SPA assets before running api.py
make dev-ui            # Optional: Vite dev server for SPA development on :5173
make dev-all           # API + Vite dev server + Discord bot together
```

Current web runtime notes:

- `python api.py` serves the API plus the built web UI at `http://127.0.0.1:8080/`.
- If `frontend/dist/` exists, FastAPI serves the built React SPA entry for `/`, `/chat`, `/topics`, `/topic/{topic_id}`, `/concepts`, `/concept/{concept_id}`, `/graph`, `/reviews`, `/forecast`, and `/actions`; otherwise those routes return a simple HTML response instructing you to run `make build-ui`.
- `make dev-ui` starts the React/Vite development server on `http://127.0.0.1:5173/`; React Router owns the SPA routes there, while backend requests are proxied to the FastAPI app on port 8080.
- `make dev-all` starts `api.py`, `npm run dev`, and `bot.py` together for a full local development stack.

## Discord Bot Setup

To use the Discord bot interface:

1. Create a new application at the [Discord Developer Portal](https://discord.com/developers/applications)
2. Go to **Bot** → **Privileged Gateway Intents** → enable **Message Content Intent**
3. Copy the bot token → set as `LEARN_BOT_TOKEN` in `.env`
4. Go to **OAuth2** → **URL Generator** → select `bot` scope with permissions: `Send Messages`, `Read Message History`
5. Open the generated URL to invite the bot to your server
6. Find your Discord User ID: enable **Developer Mode** in Discord Settings → Advanced, then right-click your username → **Copy User ID** → set as `LEARN_AUTHORIZED_USER_ID`

## Configuration

All settings are via environment variables (see [.env.example](.env.example) for the full list).

**Required (for `bot.py`):**

| Variable | Purpose |
|----------|---------|
| `LEARN_BOT_TOKEN` | Discord bot token |
| `LEARN_AUTHORIZED_USER_ID` | Your Discord user ID (current runtime remains single-user at the interface layer) |

**Required (LLM provider):**

| Variable | Example |
|----------|---------|
| `LEARN_LLM_PROVIDER` | `openai_compat` |
| `LEARN_LLM_BASE_URL` | `https://api.x.ai/v1` |
| `LEARN_LLM_API_KEY` | Your API key |
| `LEARN_LLM_MODEL` | `grok-3`, `deepseek-chat`, etc. |

For `kimi`, the CLI backend is used instead of the OpenAI-compatible settings above.

**Optional** (sensible defaults):

| Variable | Default | Purpose |
|----------|---------|---------|
| `LEARN_API_HOST` | `0.0.0.0` | REST API bind host |
| `LEARN_API_PORT` | `8080` | REST API port |
| `LEARN_API_SECRET_KEY` | _(empty)_ | API authentication secret (for `api.py`) |
| `LEARN_DB_PATH` | `data/knowledge.db` | Path to the main knowledge database |
| `LEARN_CHAT_DB_PATH` | `data/chat_history.db` | Path to the chat/session database |
| `LEARN_LLM_TEMPERATURE` | _(provider default)_ | LLM sampling temperature |
| `LEARN_LLM_MAX_TOKENS` | `4096` | Max output tokens requested from the main LLM |
| `LEARN_LLM_MAX_HISTORY_TOKENS` | `40000` | Max chat history tokens sent to LLM |
| `LEARN_LLM_THINKING` | _(model default)_ | Optional thinking-mode override for models that support it |
| `LEARN_QUIZ_STALENESS_TIMEOUT` | `15` | Minutes before stale active quiz context is auto-cleared |
| `LEARN_REVIEW_REMINDER_MAX` | `3` | Max unanswered review reminders before moving to the next concept |
| `LEARN_MAX_GRAPH_NODES` | `500` | Max concept nodes returned by graph views/endpoints before filtering |
| `LEARN_SR_INTERVAL_EXPONENT` | `0.075` | Exponent for spaced-repetition interval growth |
| `LEARN_EMBEDDING_MODEL` | `all-mpnet-base-v2` | Sentence-transformers model |
| `LEARN_VECTOR_SEARCH_LIMIT` | `10` | Default vector-search result count |
| `LEARN_SIM_DEDUP` | `0.92` | Cosine threshold for duplicate blocking |
| `LEARN_SIM_RELATION` | `0.5` | Cosine threshold for relation suggestions/search enrichment |
| `LEARN_BACKUP_DIR` | `backups/` _(project root)_ | Directory for backup snapshots |
| `LEARN_BACKUP_RETENTION_DAYS` | `7` | Days to retain backups (min: 1) |
| `LEARN_VECTOR_STORE_PATH` | `data/vectors/` | Embedded Qdrant storage path |
| `LOG_LEVEL` | `INFO` | Application log verbosity (set `DEBUG` for quiz/pipeline trace logs) |

See [.env.example](.env.example) for the full optional configuration list, including vector-search and review-cycle tuning knobs.

**Optional (Reasoning model for scheduled quiz P1):**

If configured, scheduled quizzes use a two-prompt pipeline: P1 (reasoning model) generates a structured question, P2 (main provider) packages it with persona voice. Falls back to single-prompt if not set.

| Variable | Example | Purpose |
|----------|---------|--------|
| `LEARN_REASONING_LLM_BASE_URL` | `https://api.x.ai/v1` | Reasoning model endpoint |
| `LEARN_REASONING_LLM_API_KEY` | Your key | Reasoning model API key |
| `LEARN_REASONING_LLM_MODEL` | `grok-4-1-fast-reasoning` | Reasoning model name |
| `LEARN_REASONING_LLM_THINKING` | `enabled` | Reasoning model thinking mode |

## Testing

```bash
make test
make test-ui
make test-e2e

# Fast unit-only subset
make test-fast

# Direct pytest invocation uses pyproject defaults
pytest tests/
```

`pytest` now defaults to `-n 4 --dist loadfile --tb=short` via `pyproject.toml`, so parallel execution is the standard path rather than an opt-in flag. Use `make test-fast` for the unit-marked subset when you want quicker feedback.

The React frontend has its own focused test paths:

```bash
make test-ui
# or:
cd frontend && npm run test

make test-e2e
# or:
cd frontend && npm run test:e2e
```

`npm run test:e2e` builds the SPA and runs the Playwright Chromium smoke suite against the preview server. On a fresh machine, install the browser once with `cd frontend && npx playwright install chromium`.

Tests cover the DB layer, API endpoints, parser edge cases, score guards, dedup, cycle detection, embedding service, and more. Frontend coverage now includes Vitest page tests plus Playwright browser smoke tests. Tests use isolated temporary databases and mock all external dependencies (LLM, vector store).

`make test` injects safe defaults for `LEARN_LLM_PROVIDER` and `LEARN_AUTHORIZED_USER_ID` if your shell does not already provide them.

## Admin Script

For full taxonomy reconstruction planning, use the shadow-copy rebuild script:

```bash
python scripts/taxonomy_shadow_rebuild.py
```

The script runs taxonomy mode against temporary copies of `knowledge.db`, `chat_history.db`, and the vector store, shows the recorded safe actions plus approval-gated follow-ups, then asks whether to replay only the safe actions against live data. The backup is taken inside the apply phase immediately before the first live write.

By default the script uses a more aggressive reconstruction directive than the normal weekly taxonomy run. Use `--conservative` to fall back to the standard taxonomy preamble.

Each run also exports readable topic-tree snapshots to `backups/taxonomy_shadow_rebuild/` as markdown by default:

- `live_before_latest.md` and a timestamped archive copy
- `preview_after_latest.md` and a timestamped archive copy
- `live_after_latest.md` and a timestamped archive copy after a successful apply

Useful options:

- `--yes` — skip the interactive apply confirmation
- `--max-actions N` — change the preview action budget (default: 75)
- `--structure-format txt` — export plain-text snapshots instead of markdown
- `--structure-dir PATH` — write structure snapshots to a different directory

Requirements:

- Stop the bot and API first. The project uses embedded Qdrant and SQLite files, so concurrent live processes can cause file locks or invalidate the preview baseline.
- Preview and apply run as separate fresh processes on purpose; the preview result is not a free-form fresh rerun.
- Apply aborts if the live taxonomy no longer matches the preview baseline.
- Approval-gated actions (`update_topic`, `unlink_topics`, `delete_topic`, `unlink_concept`, `update_concept`) are printed as manual follow-up only and are never auto-applied by the script.
- Restore remains manual from the backup snapshot if replay diverges or you want to roll back.

For the full operator workflow, examples, rollback steps, and Windows/OneDrive troubleshooting, see [docs/TAXONOMY_REBUILD.md](docs/TAXONOMY_REBUILD.md).

## Project Structure

```
├── bot.py                  # Discord bot entry point (thin wrapper)
├── bot/
│   ├── app.py              # Bot client setup and shared app state
│   ├── handler.py          # Core message handler (returns response, pending_action, assess_meta, quiz_meta)
│   ├── commands.py         # Slash command implementations
│   ├── events.py           # Discord event handlers
│   ├── messages.py         # Message splitting and view helpers
│   └── auth.py             # Authorization helpers
├── api.py                  # Thin FastAPI launcher for local development
├── api/                    # FastAPI app package
│   ├── app.py              # App factory, lifespan, middleware, static mounts
│   ├── auth.py             # Bearer-token and localhost auth rules
│   ├── schemas.py          # Request/response models
│   └── routes/             # API and page routers
├── config.py               # Environment-based configuration
├── frontend/               # React/Vite SPA frontend
│   ├── src/                # React routes, pages, UI primitives, API client, styles, frontend tests
│   ├── e2e/                # Playwright browser smoke tests
│   ├── dist/               # Built SPA assets served by FastAPI when present
│   ├── vite.config.ts      # Dev server and proxy config
│   └── playwright.config.ts # Browser smoke-test runner config
├── services/
│   ├── pipeline.py         # Core orchestrator (context → LLM → parse → execute)
│   ├── context.py          # Prompt/context construction
│   ├── tools.py            # Action executor (LLM JSON → DB calls)
│   ├── tools_assess.py     # Quiz/assess handlers (extracted from tools.py)
│   ├── llm.py              # LLM provider abstraction
│   ├── parser.py           # LLM response parsing
│   ├── embeddings.py       # Sentence-transformers singleton
│   ├── dedup.py            # Duplicate detection (vector + fuzzy)
│   ├── backup.py           # Snapshot backup service (DB + vectors)
│   ├── chat_session.py     # Shared chat-session controller used by FastAPI browser/API routes
│   └── ...
├── db/                     # Database package (SQLite + Qdrant)
│   ├── core.py             # Connections, schema init
│   ├── migrations.py       # Schema migrations (extracted from core.py)
│   ├── topics.py           # Topic CRUD + hierarchy
│   ├── concepts.py         # Concept CRUD + search
│   ├── vectors.py          # Qdrant wrapper
│   └── ...
├── data/
│   ├── skills/             # Modular LLM skill files (hot-reloadable)
│   ├── preferences.template.md  # Tracked default copied to runtime preferences.md on first bot startup
│   ├── preferences.md      # Runtime preferences file (local, git-ignored)
│   └── personas/           # Persona presets (buddy, coach, mentor)
├── backups/                # Timestamped backup snapshots (git-ignored)
├── scripts/                # Operator/admin scripts and test harnesses
│   ├── taxonomy_shadow_rebuild.py  # Manual taxonomy preview/apply workflow
│   └── ...
├── tests/                  # pytest test suite
└── docs/
    ├── ARCHITECTURE.md     # Full architecture documentation
    ├── DEVNOTES.md         # Bug history & architectural decisions
    ├── TAXONOMY_REBUILD.md # Manual operator guide for topic rebuilds
    └── index.md            # Knowledge base map
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Architecture diagrams, data flows, schema, module map
- [CODING.md](CODING.md) — Development guide, conventions, async/sync patterns
- [docs/DEVNOTES.md](docs/DEVNOTES.md) — Bug stories with root causes, multi-layer fixes, and design rationale
- [docs/TAXONOMY_REBUILD.md](docs/TAXONOMY_REBUILD.md) — Manual trigger guide for taxonomy preview/apply runs

## Development Approach

This project was built with LLM-assisted development — used deliberately for implementation velocity while keeping architecture decisions, quality standards, and debugging human-driven. The [CODING.md](CODING.md) onboarding guide and [DEVNOTES.md](docs/DEVNOTES.md) institutional memory document the engineering thinking behind the code.

## License

[MIT](LICENSE)
