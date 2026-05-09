# Learning Agent

A personal AI tutor that remembers what you've learned, quizzes you at the right time, and adapts to how well you know each concept.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## What it does

You chat with it naturally — ask it to explain something, have it quiz you, or just explore a topic. It builds a knowledge base from your conversations, schedules review reminders when you're likely to forget, and scores your recall to decide when each concept needs another look.

## Features

- **Spaced repetition** — Automatically schedules review quizzes based on how well you know each concept; stronger recall earns longer gaps before the next review
- **Smart quiz generation** — Generates quiz questions tailored to what you've been learning, including multi-concept questions that connect related ideas
- **Quiz skip button** — After a couple of reviews, a question you're confident about shows an "I know this" button so you don't have to type out the answer every time
- **Scheduled review reminders** — Sends you a review quiz automatically when a concept is due, with quiet hours and cooldown so it isn't disruptive
- **Knowledge graph** — Organizes everything you've learned into topics and concepts, browsable in a visual graph
- **Self-adapting notes** — The AI maintains its own running notes per concept, improving how it explains and quizzes you over time
- **Editable preferences** — `/preference` lets you read or update how the AI behaves; changes go through an explicit confirm/reject step before applying
- **Personas** — Switch between Buddy, Coach, and Mentor communication styles
- **Automatic backups** — Daily snapshots of your knowledge base; `/backup` triggers one on demand
- **Multiple interfaces** — Discord bot, browser UI, and a REST API all share the same knowledge base

## Interfaces

**Discord bot** — Chat directly in a DM or server channel. Use slash commands like `/review`, `/backup`, `/preference`, and `/reorganize`. The bot also delivers scheduled review reminders.

**Browser UI** — Open `http://localhost:8080` after starting `api.py`. Includes a chat panel, knowledge browser, concept/topic detail views, a knowledge graph, and a progress/forecast view.

**REST API** — The same backend is available as a REST API on port 8080 for programmatic access. See [docs/API.md](docs/API.md).

## Quick Start

```bash
git clone https://github.com/hychowah/INO.git
cd INO
python -m venv venv

# Activate virtual environment
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows (cmd)
.\venv\Scripts\Activate.ps1       # Windows (PowerShell)

pip install -r requirements.txt

cp .env.example .env              # Windows: copy .env.example .env
```

> **Note:** `sentence-transformers` pulls in PyTorch (~2 GB). For a CPU-only install, run `pip install torch --index-url https://download.pytorch.org/whl/cpu` before `pip install -r requirements.txt`.

Edit `.env` with at minimum:

```dotenv
LEARN_LLM_BASE_URL=https://api.x.ai/v1    # any OpenAI-compatible endpoint
LEARN_LLM_API_KEY=your_api_key_here
LEARN_LLM_MODEL=grok-3
LEARN_BOT_TOKEN=your_discord_bot_token     # Discord bot only
LEARN_AUTHORIZED_USER_ID=your_discord_user_id
```

Then run:

```bash
python bot.py      # Discord bot
python api.py      # Browser UI + REST API at http://localhost:8080
make dev-all       # Both together, plus the Vite dev server
```

For the full setup walkthrough (frontend build, Node.js dependencies, `.env` reference): see [docs/SETUP.md](docs/SETUP.md).

## Discord Bot Setup

1. Create a new application at the [Discord Developer Portal](https://discord.com/developers/applications)
2. Go to **Bot** → **Privileged Gateway Intents** → enable **Message Content Intent**
3. Copy the bot token → set as `LEARN_BOT_TOKEN` in `.env`
4. Go to **OAuth2** → **URL Generator** → select `bot` scope with permissions: `Send Messages`, `Read Message History`
5. Open the generated URL to invite the bot to your server
6. Find your Discord User ID: enable **Developer Mode** in Discord Settings → Advanced, then right-click your username → **Copy User ID** → set as `LEARN_AUTHORIZED_USER_ID`

## Configuration

All settings are environment variables in `.env`. The required ones are:

| Variable | Purpose |
|----------|---------|
| `LEARN_LLM_BASE_URL` | Your LLM provider endpoint (any OpenAI-compatible URL) |
| `LEARN_LLM_API_KEY` | LLM API key |
| `LEARN_LLM_MODEL` | Model name (e.g. `grok-3`, `deepseek-chat`) |
| `LEARN_BOT_TOKEN` | Discord bot token (Discord bot only) |
| `LEARN_AUTHORIZED_USER_ID` | Your Discord user ID (Discord bot only) |

For the full list of optional settings (review timing, backup retention, quiet hours, vector search tuning, etc.): see [docs/SETUP.md](docs/SETUP.md) or [.env.example](.env.example).

## Testing

```bash
make test
```

See [docs/SETUP.md](docs/SETUP.md) for frontend and end-to-end test instructions.

## Documentation

| Doc | Contents |
|-----|---------|
| [docs/SETUP.md](docs/SETUP.md) | Full install guide, all config variables, frontend build |
| [docs/API.md](docs/API.md) | Discord commands and REST API reference |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flow, and module map |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

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


## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Architecture diagrams, data flows, schema, module map
- [CODING.md](CODING.md) — Development guide, conventions, async/sync patterns
- [docs/DEVNOTES.md](docs/DEVNOTES.md) — Bug stories with root causes, multi-layer fixes, and design rationale
- [docs/TAXONOMY_REBUILD.md](docs/TAXONOMY_REBUILD.md) — Manual trigger guide for taxonomy preview/apply runs

