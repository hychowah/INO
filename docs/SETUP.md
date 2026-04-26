# Local Development Setup

This guide walks you through setting up a fully functional local development environment for the Learning Agent.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | 3.12 recommended |
| pip | latest | `pip install --upgrade pip` |
| git | any | |
| Node.js | 18+ | Required for the React frontend (`npm`) |
| Discord account | — | Required for bot testing |
| LLM API key | — | Any OpenAI-compatible provider |

---

## 1. Clone and Create Virtual Environment

```bash
git clone https://github.com/hychowah/INO.git
cd INO

python -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows (cmd)
.\venv\Scripts\Activate.ps1       # Windows (PowerShell)
```

---

## 2. Install Dependencies

```bash
# Runtime dependencies
pip install -r requirements.txt

# Development / test / lint dependencies
pip install -r requirements-dev.txt
```

> **Note on PyTorch / sentence-transformers:** `sentence-transformers` pulls in PyTorch (~2 GB).
> For a CPU-only install, run the following *before* `pip install -r requirements.txt`:
>
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> ```

---

## 2b. Install Frontend Dependencies

```bash
cd frontend
npm install
cd ..
```

> **Node.js required.** This installs the React/TypeScript/Vite SPA frontend, including Tailwind CSS tooling and Playwright test dependencies.
> Run this once before `make dev-ui`, `make build-ui`, `make test-ui`, or `make dev-all`.

---

## 3. Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```ini
# LLM backend (required)
LEARN_LLM_PROVIDER=openai_compat
LEARN_LLM_BASE_URL=https://api.x.ai/v1
LEARN_LLM_API_KEY=your-api-key
LEARN_LLM_MODEL=grok-3

# Discord (required for bot)
LEARN_BOT_TOKEN=your-discord-bot-token
LEARN_AUTHORIZED_USER_ID=your-discord-user-id   # numeric ID

# Current shipped runtime is still single-user at the interface layer.
# The internal DB user_id scaffolding is present but not yet activated at entry points.

# REST API settings (required for api.py unless you use the defaults shown)
# LEARN_API_HOST=0.0.0.0
# LEARN_API_PORT=8080
LEARN_API_SECRET_KEY=choose-a-secret-token

# Database paths (optional — repo-relative or absolute)
# LEARN_DB_PATH=data/knowledge.db
# LEARN_CHAT_DB_PATH=data/chat_history.db

# LLM output/tuning (optional)
# LEARN_LLM_MAX_TOKENS=4096
# LEARN_LLM_THINKING=disabled
# LEARN_LLM_TEMPERATURE=0.7
# LEARN_LLM_MAX_HISTORY_TOKENS=40000
# LEARN_LLM_OUTPUT_MODE=auto         # auto | json_object | json_schema | legacy
# LEARN_LLM_FAILURE_LOG_DIR=data/llm_failures
# LEARN_LLM_LOG_FAILURE_RAW=1        # set 0 to store snippets instead of full raw malformed output

# Quiz/review safety knobs (optional)
# LEARN_QUIZ_STALENESS_TIMEOUT=15
# LEARN_REVIEW_REMINDER_MAX=3
# LEARN_MAX_GRAPH_NODES=500

# Backup settings (optional)
# LEARN_BACKUP_DIR=backups              # Directory for timestamped backup snapshots (default: backups/)
# LEARN_BACKUP_RETENTION_DAYS=7        # Number of days to keep old backups before pruning (minimum: 1)

# Spaced repetition interval tuning (optional)
# LEARN_SR_INTERVAL_EXPONENT=0.075     # interval = e^(score×K); tune cautiously because growth is exponential

# Embeddings / hybrid search (optional)
# LEARN_EMBEDDING_MODEL=all-mpnet-base-v2
# LEARN_VECTOR_SEARCH_LIMIT=10
# LEARN_SIM_DEDUP=0.92
# LEARN_SIM_RELATION=0.5

# Logging (optional)
# LOG_LEVEL=INFO    # Set to DEBUG to enable verbose [quiz_anchor] and pipeline trace logs
```

See `.env.example` for the complete variable reference.

---

## 4. Embedded Vector Store

Qdrant runs in embedded mode by default — no separate server or URL configuration is required. The first run automatically initialises the embedded database under `data/vectors/`.

The application degrades gracefully if embeddings or vector storage are unavailable: it falls back to SQLite FTS5 full-text search.

---

## 5. Run Tests

```bash
make test
# runs `pytest tests/` with safe env defaults injected by the Makefile

# Fast unit-only subset
make test-fast

# Single-threaded override if needed for debugging
python -m pytest tests/ -n 0
```

To run the React frontend tests (Vitest + Testing Library — no venv required):

```bash
make test-ui
# equivalent to: cd frontend && npm run test
```

To run the browser smoke tests for the frontend preview build:

```bash
make test-e2e
# equivalent to: cd frontend && npm run test:e2e
```

On a fresh machine, install the Playwright browser once before the first E2E run:

```bash
cd frontend
npx playwright install chromium
```

The test suite uses mocked LLM responses plus isolated temporary SQLite database copies seeded from the shared fixtures in `tests/conftest.py` — no real API keys or Discord tokens are required. `make test` also injects safe default values for `LEARN_LLM_PROVIDER` and `LEARN_AUTHORIZED_USER_ID` when they are missing. Parallel execution is the default through `pyproject.toml` (`-n 4 --dist loadfile --tb=short`), while `make test-fast` runs only tests marked `unit`.

The Python CI workflow in `.github/workflows/tests.yml` now runs a `pytest --collect-only tests/` guard on Python 3.12 before the full matrix test run so non-test scripts cannot silently slip back under `tests/`.

---

## 6. Lint and Format

```bash
# Check for lint errors
make lint        # ruff check . && ruff format --check .

# Auto-format code
make format      # ruff format .
```

Ruff is configured in `pyproject.toml`.

---

## 7. Start the Application

### Discord Bot

```bash
make run-bot
# equivalent to: python bot.py
```

The bot connects to Discord and registers slash commands on startup. Use `/sync` (in Discord) the first time you run it to publish commands to your server.

### FastAPI Backend

```bash
make run-api
# equivalent host/port to: python api.py
# defaults to LEARN_API_PORT=8080 unless overridden in .env
```

- API docs: `http://localhost:8080/docs`
- Health check: `http://localhost:8080/api/health`

### React Frontend (Vite dev server)

```bash
make dev-ui
# equivalent to: cd frontend && npm run dev
```

- Opens the React SPA at `http://127.0.0.1:5173`
- React Router owns the SPA routes in dev mode; backend requests are proxied to FastAPI on `http://127.0.0.1:8080`
- The current Vite proxy covers `/api`, `/assets`, and `/static`; browser navigation for SPA routes stays inside the Vite app
- Requires the FastAPI backend (`make run-api`) to be running

To build the production frontend (FastAPI serves the built SPA for HTML requests outside `/api`, `/assets`, and `/static`, with canonical routes under `/`, `/chat`, `/knowledge`, `/knowledge/concepts`, `/knowledge/graph`, `/progress`, `/progress/forecast`, `/topic/{topic_id}`, `/concept/{concept_id}`, and `/actions`):

```bash
make build-ui
# equivalent to: cd frontend && npm run build
```

Legacy `/topics`, `/concepts`, `/graph`, `/reviews`, and `/forecast` paths remain available as SPA compatibility redirects after the build is served by FastAPI.

These same frontend commands are also exercised in `.github/workflows/frontend.yml`, which typechecks the frontend, runs Vitest, installs the Chromium Playwright browser, and runs the browser smoke suite so local validation matches CI.

### Run Everything at Once

```bash
make dev-all
# starts API (:8080), React dev server (:5173), and Discord bot together
# optional flags: python scripts/dev_all.py --no-bot  or  --no-ui
```

There is no longer a separate companion Web UI. Use the FastAPI-served built frontend on `:8080` or the Vite dev server on `:5173`.

---

## 8. Project Structure Quick Reference

```
INO/
├── bot.py              # Discord bot entry point
├── api.py              # FastAPI backend entry point
├── config.py           # Shared configuration and env-var loading
├── backups/            # Runtime-generated — timestamped backup snapshots (git-ignored)
├── db/                 # SQLite database access layer
├── services/           # Core business logic (pipeline, tools, tools_assess, context, …)
├── frontend/           # React/TypeScript/Vite browser frontend
├── data/
│   ├── skills/         # LLM skill files (hot-reloadable)
│   ├── preferences.template.md  # Tracked default copied to runtime preferences.md on first bot startup
│   ├── preferences.md  # Runtime preferences file (local, git-ignored)
│   └── personas/       # Persona presets (mentor, coach, buddy)
├── tests/              # pytest test suite
│   ├── ...             # Includes route-focused API tests, tool-handler tests, and frontend-aligned backend coverage
├── frontend/
│   ├── src/            # Routes, pages, API client, Tailwind styles, local UI primitives, frontend tests
│   ├── e2e/            # Playwright browser smoke tests
│   └── package.json    # npm scripts and frontend dependencies
├── scripts/            # Operational scripts, migrations, and manual smoke paths
│   ├── maintenance_smoke.py   # Manual maintenance/dedup smoke script (not part of pytest)
│   ├── test_quiz_generator.py # Manual quiz-generator harness with pytest companion coverage
│   └── test_similarity.py     # Manual similarity harness
├── docs/               # Developer documentation
│   ├── ARCHITECTURE.md
│   ├── API.md          # API reference
│   ├── SETUP.md        # This file
│   └── DEVNOTES.md
├── .github/workflows/  # CI workflows (tests, lint, frontend)
├── pyproject.toml      # pytest + Ruff configuration
├── requirements.txt    # Runtime dependencies
└── requirements-dev.txt # Development/test/lint dependencies
```

---

## 9. Available Discord Commands

| Command | Purpose |
|---------|---------|
| `/learn [text]` | Chat with the learning coach, ask questions, or start a quiz flow. |
| `/review` | Pull the next due review quiz. Concepts with 2+ prior reviews can show an `I know this` skip button, and unanswered single-concept reviews remain recoverable from persisted pending-review state even if the volatile quiz anchor times out. |
| `/due` | List concepts currently due for review. |
| `/topics` | Show the current topic hierarchy and knowledge map. |
| `/persona [name]` | Show or switch persona (`mentor`, `coach`, `buddy`). |
| `/maintain` | Run manual maintenance diagnostics when `LEARN_ENABLE_MAINTENANCE=1`; otherwise it reports that maintenance is disabled. |
| `/reorganize` | Run the taxonomy reorganization pass and review any proposed structural changes. |
| `/preference [text]` | Show the current runtime `preferences.md`, or propose an LLM-generated edit with Apply/Reject buttons. |
| `/backup` | Run an on-demand backup of all databases and the vector store. |
| `/clear` | Clear the current channel's saved chat history. |
| `/ping` | Check that the bot is alive and responding. |
| `/sync` | Admin command to sync slash commands with Discord. |

For endpoint and feature details, see [API.md](API.md).

---

## 10. Common Issues

### `ModuleNotFoundError: No module named 'discord'`
Run `pip install -r requirements.txt` inside your active virtual environment.

### Tests fail with `KeyError` on env vars
The test suite sets safe dummy values for `LEARN_LLM_PROVIDER` and `LEARN_AUTHORIZED_USER_ID`. If you run pytest directly, set them:
```bash
LEARN_LLM_PROVIDER=openai_compat LEARN_LLM_BASE_URL=https://api.test/v1 LEARN_LLM_API_KEY=test-key LEARN_LLM_MODEL=test-model LEARN_AUTHORIZED_USER_ID=123456789 pytest tests/
```
Or use `make test`, which injects the same safe defaults automatically.

### `sentence-transformers` takes a long time to download
The model (`all-mpnet-base-v2`, ~420 MB) is downloaded once on first use and cached in `~/.cache/huggingface/`. Subsequent starts are fast.

### Discord slash commands not showing
Run `/sync` in your Discord server after starting the bot for the first time, or after adding new commands.

---

## 11. Scripts

| Script | Purpose |
|--------|---------|
| `scripts/dev_all.py` | Run the full local dev stack: API + React frontend dev server + Discord bot |
| `scripts/agent.py` | Run the standalone maintenance agent |
| `scripts/maintenance_smoke.py` | Manual maintenance + dedup smoke script against live local data; intentionally not part of pytest/CI |
| `scripts/live_output_contract_smoke.py` | Manual real-provider smoke test using local `.env`; validates structured output, malformed-output retry, and full pipeline safety |
| `scripts/migrate_vectors.py` | Migrate vector embeddings between Qdrant collections |
| `scripts/test_quiz_generator.py` | Manual integration test for quiz generation (paired with `tests/test_quiz_generator_script.py` for CI-safe coverage) |
| `scripts/test_similarity.py` | Manual integration test for similarity search (not in pytest suite) |

> **Note:** `scripts/test_similarity.py`, `scripts/maintenance_smoke.py`, and `scripts/live_output_contract_smoke.py` remain intentionally manual because they operate against live local state or real provider credentials. `scripts/test_quiz_generator.py` still exists as a manual harness, but CI-safe companion coverage now lives in `tests/test_quiz_generator_script.py`.

### Live LLM Output-Contract Smoke Test

When switching providers/models, validate the live `.env` configuration before trusting interactive chat output:

```bash
python scripts/live_output_contract_smoke.py
python scripts/live_output_contract_smoke.py --show-raw
python scripts/live_output_contract_smoke.py --skip-pipeline
```

This script calls the configured real provider, checks the structured-output path, forces a malformed-output retry, and runs a full `call_with_fetch_loop()` smoke test. A controlled formatting failure is considered safe; raw action/reasoning leakage is not.
