# CODING.md — Development Instructions for AI Coding Assistants

> **Audience:** Copilot, Claude, Cursor, and human developers editing this codebase.
> **NOT for:** The runtime LLM — that reads `AGENTS.md` only.
>
> **Also read:** `docs/DEVNOTES.md` for bug history and architecture decisions before making changes.

---

## Project Overview

A personal learning coach with spaced repetition. Two entry points talk to the same pipeline:

```
bot.py  (Discord)  ─┐
                     ├──→  services/pipeline.py  →  services/tools.py  →  db/
api.py  (FastAPI)   ─┘
```

The runtime LLM (DeepSeek/Grok/kimi) is the brain — it decides what to teach, when to quiz, and how to adapt. The code is a thin executor: parse LLM JSON → call DB → return result.

---

## Project Structure

```
ROOT
├── AGENTS.md              # Runtime LLM system prompt (DO NOT mix dev instructions here)
├── preferences.md         # Runtime LLM user preferences
├── config.py              # All settings, loads .env via python-dotenv
├── bot.py                 # Entry point: Discord bot
├── api.py                 # Entry point: FastAPI REST API
├── requirements.txt
│
├── services/              # All business logic
│   ├── pipeline.py        # Orchestration: LLM calls, fetch loop, action execution
│   ├── tools.py           # Action executor: maps LLM verbs → DB calls
│   ├── context.py         # Prompt builder: dynamic context for LLM calls
│   ├── parser.py          # LLM response parsing and output classification
│   ├── llm.py             # LLM provider abstraction (kimi-cli, OpenAI-compat)
│   ├── scheduler.py       # Background review/maintenance scheduler (Discord only)
│   ├── state.py           # Shared mutable state (avoids circular imports)
│   ├── dedup.py           # Duplicate concept detection sub-agent
│   ├── repair.py          # Malformed action repair sub-agent
│   └── kimi.py            # kimi-cli specific helpers
│
├── db/                    # Database layer (SQLite)
│   ├── core.py            # Connections, init, migrations, datetime utils
│   ├── topics.py          # Topic CRUD, topic maps
│   ├── concepts.py        # Concept CRUD, search, detail views
│   ├── reviews.py         # Review log, remarks
│   ├── chat.py            # Chat history, session state
│   ├── preferences.py     # Persona selection (get/set via session_state)
│   ├── diagnostics.py     # Maintenance diagnostics
│   └── __init__.py        # Re-exports all public functions
│
├── data/
│   └── personas/          # Persona preset .md files (mentor, coach, buddy)
│
├── tests/                 # Manual test scripts (not pytest)
├── webui/                 # Standalone web UI for DB browsing
├── docs/                  # ARCHITECTURE.md, DEVNOTES.md, PLAN.md
├── scripts/               # start.bat, start_api.bat, agent.py (legacy CLI)
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

## How to Add a New Action

1. **`services/tools.py`** — Write `_handle_<name>(params: dict) -> tuple[str, Any]`:
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

3. **`AGENTS.md`** — Add documentation with a **concrete JSON example** (critical — the LLM will hallucinate the structure without one). Mark examples with `<!-- DO NOT REMOVE -->`.

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

Tests are manual scripts in `tests/`, not pytest:
```bash
python tests/test_dedup.py
```
They use `print()` output, not assertions. Run manually and inspect.

---

## Key Files You Should NOT Edit Casually

| File | Risk | Why |
|------|------|-----|
| `AGENTS.md` | **High** | Runtime LLM prompt. Every word affects behavior. Test changes by chatting with the bot. See DEVNOTES §1 for past formatting bugs. **No tone/style directives here** — those go in persona files. |
| `preferences.md` | **Medium** | User preferences injected into every LLM call. |
| `data/personas/*.md` | **Medium** | Persona presets. Changes reflected without restart (mtime cache). Token budget: ~600 tokens max per file. |
| `db/core.py` migrations | **High** | Schema migrations are append-only. Never modify existing migration blocks. |
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
