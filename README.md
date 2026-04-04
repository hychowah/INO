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
- **Dual interfaces** — Discord bot (`bot.py` wrapper + `bot/` package) and REST API (`api.py`) share the same pipeline
- **Knowledge graph** — DAG-based topic hierarchy with many-to-many concept mapping
- **Web dashboard** — Zero-dependency read-only HTTP UI with interactive D3.js topic tree and force-directed graph
- **Automated maintenance** — Background agent for DB health triage, duplicate detection, and knowledge base cleanup
- **Configurable personas** — Buddy / Coach / Mentor presets loaded from Markdown files
- **Defense-in-depth** — Prompt rules + code guards + temptation reduction to prevent score inflation, phantom adds, and duplicates

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  User Interfaces                                                │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────────┐  │
│  │ Discord Bot │  │  REST API  │  │  Web UI (read-only :8050)│  │
│  │  bot.py     │  │  api.py    │  │  webui/server.py         │  │
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
| Web UI | Vanilla JS + D3.js (zero build step) |

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
python bot.py          # Discord bot (+ web dashboard on :8050)
python api.py          # REST API only (http://localhost:8080)
```

The web dashboard starts automatically with the Discord bot on port 8050. To run it standalone: `python -m webui.server`.

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
| `LEARN_AUTHORIZED_USER_ID` | Your Discord user ID (restricts access to you) |

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
| `LEARN_API_PORT` | `8080` | REST API port |
| `LEARN_API_SECRET_KEY` | _(empty)_ | API authentication secret (for `api.py`) |
| `LEARN_LLM_TEMPERATURE` | _(provider default)_ | LLM sampling temperature |
| `LEARN_LLM_MAX_HISTORY_TOKENS` | `40000` | Max chat history tokens sent to LLM |
| `LEARN_EMBEDDING_MODEL` | `all-mpnet-base-v2` | Sentence-transformers model |
| `LEARN_SIM_DEDUP` | `0.92` | Cosine threshold for duplicate blocking |

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
pytest tests/ -v
```

Tests cover the DB layer, API endpoints, parser edge cases, score guards, dedup, cycle detection, embedding service, and more. Tests use isolated temporary databases and mock all external dependencies (LLM, vector store).

`make test` injects safe defaults for `LEARN_LLM_PROVIDER` and `LEARN_AUTHORIZED_USER_ID` if your shell does not already provide them.

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
├── api.py                  # FastAPI REST entry point
├── config.py               # Environment-based configuration
├── services/
│   ├── pipeline.py         # Core orchestrator (context → LLM → parse → execute)
│   ├── context.py          # Prompt/context construction
│   ├── tools.py            # Action executor (LLM JSON → DB calls)
│   ├── tools_assess.py     # Quiz/assess handlers (extracted from tools.py)
│   ├── llm.py              # LLM provider abstraction
│   ├── parser.py           # LLM response parsing
│   ├── embeddings.py       # Sentence-transformers singleton
│   ├── dedup.py            # Duplicate detection (vector + fuzzy)
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
│   └── personas/           # Persona presets (buddy, coach, mentor)
├── webui/                  # Zero-dependency web dashboard
│   ├── server.py           # HTTP server + routing
│   ├── helpers.py          # HTML helpers (extracted from server.py)
│   └── pages.py            # Page renderers (extracted from server.py)
├── tests/                  # pytest test suite
└── docs/
    ├── architecture.md     # Full architecture documentation
    ├── DEVNOTES.md         # Bug history & architectural decisions
    └── index.md            # Knowledge base map
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Architecture diagrams, data flows, schema, module map
- [CODING.md](CODING.md) — Development guide, conventions, async/sync patterns
- [docs/DEVNOTES.md](docs/DEVNOTES.md) — Bug stories with root causes, multi-layer fixes, and design rationale

## Development Approach

This project was built with LLM-assisted development — used deliberately for implementation velocity while keeping architecture decisions, quality standards, and debugging human-driven. The [CODING.md](CODING.md) onboarding guide and [DEVNOTES.md](docs/DEVNOTES.md) institutional memory document the engineering thinking behind the code.

## License

[MIT](LICENSE)
