# Local Development Setup

This guide walks you through setting up a fully functional local development environment for the Learning Agent.

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | 3.12 recommended |
| pip | latest | `pip install --upgrade pip` |
| git | any | |
| Discord account | — | Required for bot testing |
| LLM API key | — | `kimi` CLI or any OpenAI-compatible provider |

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

## 3. Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```ini
# LLM backend (required)
# For kimi CLI: set LEARN_LLM_PROVIDER=kimi or omit it entirely.
LEARN_LLM_PROVIDER=kimi

# For OpenAI-compatible providers instead, use:
# LEARN_LLM_PROVIDER=openai_compat
# LEARN_LLM_BASE_URL=https://api.x.ai/v1
# LEARN_LLM_API_KEY=your-api-key
# LEARN_LLM_MODEL=grok-3

# Discord (required for bot)
LEARN_BOT_TOKEN=your-discord-bot-token
LEARN_AUTHORIZED_USER_ID=your-discord-user-id   # numeric ID

# REST API token (required for api.py)
LEARN_API_SECRET_KEY=choose-a-secret-token

# Database paths (optional — repo-relative or absolute)
# LEARN_DB_PATH=data/knowledge.db
# LEARN_CHAT_DB_PATH=data/chat_history.db

# Backup settings (optional)
# LEARN_BACKUP_DIR=backups              # Directory for timestamped backup snapshots (default: backups/)
# LEARN_BACKUP_RETENTION_DAYS=7        # Number of days to keep old backups before pruning (minimum: 1)

# Spaced repetition interval tuning (optional)
# LEARN_SR_INTERVAL_EXPONENT=0.05    # interval = e^(score×K): score=50→~12d, score=100→~148d

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
# equivalent to: python -m pytest tests/ -v --tb=short

# Optional: parallel execution (~3x faster on multi-core machines)
python -m pytest tests/ -n auto
```

The test suite uses mocked LLM responses and an in-memory SQLite database — no real API keys or Discord tokens are required. `make test` also injects safe default values for `LEARN_LLM_PROVIDER` and `LEARN_AUTHORIZED_USER_ID` when they are missing.

---

## 6. Lint and Format

```bash
# Check for lint errors
make lint        # ruff check .

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
It also starts the read-only Web UI on `http://localhost:8050` after the bot reaches `on_ready()`.

### FastAPI Backend

```bash
make run-api
# equivalent host/port to: python api.py
# defaults to LEARN_API_PORT=8080 unless overridden in .env
```

- API docs: `http://localhost:8080/docs`
- Health check: `http://localhost:8080/api/health`

### Web UI Dashboard

```bash
python webui/server.py
```

Open `http://localhost:8050` in your browser. This standalone command is optional if you already started `python bot.py`, because the bot launches the same Web UI server automatically.

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
├── webui/              # Read-only web dashboard
│   ├── server.py       # HTTP server + routing
│   ├── helpers.py      # HTML helpers (extracted from server.py)
│   ├── pages.py        # Page renderers (extracted from server.py)
│   └── static/         # JS and CSS assets
├── data/
│   ├── skills/         # LLM skill files (hot-reloadable)
│   └── personas/       # Persona presets (mentor, coach, buddy)
├── tests/              # pytest test suite
├── scripts/            # Operational scripts (migrations, manual tests)
├── docs/               # Developer documentation
│   ├── ARCHITECTURE.md
│   ├── API.md          # API reference
│   ├── SETUP.md        # This file
│   └── DEVNOTES.md
├── .github/workflows/  # CI workflows (tests, lint)
├── pyproject.toml      # pytest + Ruff configuration
├── requirements.txt    # Runtime dependencies
└── requirements-dev.txt # Development/test/lint dependencies
```

---

## 9. Available Discord Commands

| Command | Purpose |
|---------|---------|
| `/learn [text]` | Chat with the learning coach, ask questions, or start a quiz flow. |
| `/review` | Pull the next due review quiz. Concepts with 2+ prior reviews can show an `I know this` skip button. |
| `/due` | List concepts currently due for review. |
| `/topics` | Show the current topic hierarchy and knowledge map. |
| `/persona [name]` | Show or switch persona (`mentor`, `coach`, `buddy`). |
| `/maintain` | Run manual maintenance diagnostics and cleanup suggestions. |
| `/backup` | Run an on-demand backup of all databases and the vector store. |
| `/clear` | Clear the current channel's saved chat history. |
| `/sync` | Admin command to sync slash commands with Discord. |

For endpoint and feature details, see [API.md](API.md).

---

## 10. Common Issues

### `ModuleNotFoundError: No module named 'discord'`
Run `pip install -r requirements.txt` inside your active virtual environment.

### Tests fail with `KeyError` on env vars
The test suite sets safe dummy values for `LEARN_LLM_PROVIDER` and `LEARN_AUTHORIZED_USER_ID`. If you run pytest directly, set them:
```bash
LEARN_LLM_PROVIDER=kimi LEARN_AUTHORIZED_USER_ID=123456789 pytest tests/
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
| `scripts/agent.py` | Run the standalone maintenance agent |
| `scripts/migrate_vectors.py` | Migrate vector embeddings between Qdrant collections |
| `scripts/test_quiz_generator.py` | Manual integration test for quiz generation (not in pytest suite) |
| `scripts/test_similarity.py` | Manual integration test for similarity search (not in pytest suite) |

> **Note:** `scripts/test_quiz_generator.py` and `scripts/test_similarity.py` are manual integration scripts that require live API keys. They live in `scripts/` rather than `tests/` because they cannot run in CI without real credentials. A future PR will add proper mock-based versions to `tests/`.
