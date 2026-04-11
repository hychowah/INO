# Changelog — Learning Agent

Key changes, newest first.

---

## April 2026

### Added

- **Taxonomy shadow rebuild** (`scripts/taxonomy_shadow_rebuild.py`, `docs/TAXONOMY_REBUILD.md`) — operator workflow that previews taxonomy changes against shadow copies of the live DBs/vector store, records replayable safe actions, writes before/after structure snapshots, and replays safe actions against live data after a backup; driven by `call_taxonomy_loop()` with `max_actions`, `action_journal`, and `operator_directive` hooks
- **Backup service** (`services/backup.py`, `/backup` slash command) — snapshots `knowledge.db`, `chat_history.db`, and `data/vectors/` into a timestamped directory; prunes snapshots older than `LEARN_BACKUP_RETENTION_DAYS` (default: 7); runs on every weekly maintenance cycle; on-demand via `/backup`
- **`/preference` command** with LLM-driven editing (`data/skills/preferences.md`, `SKILL_SETS["preference-edit"]`) — no-arg mode displays runtime `data/preferences.md`; text mode routes through an isolated LLM edit flow and shows Apply/Reject buttons (`PreferenceUpdateView`) before writing
- **`/reorganize` command** — manually triggers the taxonomy reorganization agent for the authorized user; also runs weekly via scheduler
- **`data/skills/taxonomy.md`** and `SKILL_SETS["taxonomy"]` — LLM skill file for the taxonomy reorganization agent; covers topic tree restructuring, grouping rules, and suppressed-rename handling
- **Quiz metadata footer** (`format_quiz_metadata()` in `services/formatting.py`) — every quiz question now shows concept title, mastery score, and review count; includes skip-unlock hint when `review_count < 2`
- **Confirmable actions whitelist** in `/api/chat/confirm` and `/api/chat/decline` — only `add_concept`, `suggest_topic`, `add_topic`, `link_concept` may be confirmed/declined via REST; any other action returns HTTP 400
- **`/api/chat/decline`** endpoint (`api/routes/chat.py`) — declines a pending action from `/api/chat` and records a decline history entry; uses the same `ConfirmRequest` schema and `API_CONFIRMABLE_ACTIONS` whitelist as `/confirm`
- **`is_quiz_active()`** helper in `services/pipeline.py` — single source of truth for whether a quiz session is currently active (guards `assess` and `multi_assess` actions)
- **Stable isolated taxonomy sessions** in `services/pipeline.py` — taxonomy-mode reuses one isolated LLM session across the action loop
- **`call_action_loop()`** in `services/pipeline.py` — generic LLM action loop shared by maintenance and taxonomy
- **`[quiz_anchor]` debug logs** — trace lines in `context.py`, `tools_assess.py`, and `pipeline.py`; visible at `LOG_LEVEL=DEBUG`
- **Web UI chat interface** (`webui/chat_backend.py`, `webui/pages/chat.py`, `/chat` route) — in-process chat backend that runs alongside the Web UI without requiring a separate FastAPI server; parallels the REST `/api/chat`, `/api/chat/confirm`, and `/api/chat/decline` flows via `handle_webui_message`, `confirm_webui_action`, and `decline_webui_action` (uses a distinct `WEBUI_CONFIRMABLE_ACTIONS` whitelist)
- Parallel pytest: `pytest-xdist[psutil]>=3.0`, `-n 4 --dist loadfile` default, `make test-fast` target

### Fixed

- **OpenAI blocking-import fix** (`services/llm.py`) — `from openai import AsyncOpenAI` and `import openai.resources.chat` moved to module level; pre-warms the full lazy-import cascade at Python startup so the asyncio event loop is never blocked on the first LLM call; `_OPENAI_AVAILABLE` flag also promoted to module level; regression tests added in `TestOpenAIClientConstructionPath` and `test_openai_submodules_pre_imported`
- **Quiz staleness UTC mismatch** — `_is_quiz_stale()` compared local `datetime.now()` against SQLite `CURRENT_TIMESTAMP` (UTC); in UTC+8 this made every quiz appear ~8 hours stale immediately, clearing the quiz anchor and blocking all `assess` actions — fixed by switching to `datetime.now(timezone.utc).replace(tzinfo=None)`
- **`assess`/`multi_assess` guard** — both actions are now blocked when no quiz is active; `execute_action` returns a `REPLY:` message instead of mutating scores
- **`/review` quiz anchor loss** — command now pre-sets `quiz_anchor_concept_id` before executing the LLM response, preventing anchor loss on the first assess turn
- **`send_long_with_view()`** omits the `view=` kwarg entirely when `view` is `None`; Discord raises `TypeError` when `view=None` is passed explicitly
- **Backup Windows file-lock retry** — `services/backup.py` retries temp-directory promotion on transient `PermissionError` (OneDrive/Defender on freshly copied vector-store files)
- **Test isolation** — `db.chat.CHAT_DB` patched in `conftest.py` alongside `db.core.CHAT_DB`, fixing leakage between test cases

### Changed

- **`MAINTENANCE_INTERVAL_HOURS`** changed from `24` to `168` — maintenance, taxonomy, dedup, and backup now run weekly instead of daily
- **`ProposedActionsView`** (renamed from `MaintenanceConfirmView`) — now shared by both maintenance and taxonomy approval flows

### Refactored

- Extracted `db/migrations.py` (~265 lines) from `db/core.py` — all schema migration blocks
- Extracted `webui/helpers.py` (~145 lines), `webui/pages/` package (~950 lines), and `webui/chat_backend.py` (~430 lines) from `webui/server.py`
- Extracted `services/tools_assess.py` (~360 lines) from `services/tools.py` — quiz/assess action handlers

---

## Initial Release

### Added

- Discord bot entry point (`bot.py`) with LLM-driven spaced repetition
- FastAPI REST backend (`api.py`) with topic/concept/review CRUD
- Read-only Web UI dashboard (`webui/server.py`) with D3.js graph visualisation
- SQLite-based persistence (`db/`) with WAL mode
- Qdrant embedded vector store for hybrid semantic + FTS5 search
- Modular LLM prompt system (`data/skills/`) with hot-reloadable skill files
- Configurable personas (`data/personas/`)
- Automated maintenance agent (`services/scheduler.py`)
- Comprehensive test suite (`tests/`)
