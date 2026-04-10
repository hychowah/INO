# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `scripts/taxonomy_shadow_rebuild.py` — operator-facing taxonomy rebuild workflow; previews taxonomy changes against shadow copies of the live DBs/vector store, records replayable safe actions, writes before/after structure snapshots, then replays safe actions against live data after an immediate backup
- `docs/TAXONOMY_REBUILD.md` — manual operator guide covering preview vs apply, aggressive vs conservative mode, structure exports, backup behavior, rollback, and Windows/OneDrive troubleshooting
- `tests/test_taxonomy_shadow_rebuild.py` — focused coverage for taxonomy shadow rebuild helpers, replay validation, structure exports, and taxonomy loop parameter forwarding
- `LEARN_VECTOR_STORE_PATH` env var (`config.py`) — overrides the embedded Qdrant storage path, enabling shadow-copy taxonomy preview runs against temporary vector-store directories
- `call_taxonomy_loop(..., max_actions=, continuation_context_limit=, action_journal=, operator_directive=)` in `services/pipeline.py` — script hooks for aggressive taxonomy rebuilds, action journaling, and larger preview budgets
- stable isolated taxonomy sessions in `services/pipeline.py` — taxonomy-mode now reuses one isolated LLM session across the action loop instead of piggybacking on the interactive conversation session
- markdown/plain-text taxonomy structure exports under `backups/taxonomy_shadow_rebuild/` — `live_before`, `preview_after`, and `live_after` snapshots with latest + timestamped archive copies
- `services/backup.py` — new backup service; snapshots `knowledge.db`, `chat_history.db`, and `data/vectors/` into a timestamped subdirectory under `backups/` (or `LEARN_BACKUP_DIR`); prunes snapshots older than `LEARN_BACKUP_RETENTION_DAYS` (default: 7); atomic write pattern ensures no partial backup is left on failure
- `/backup` slash command in `bot/commands.py` — on-demand backup for the authorized user; defers interaction, runs `backup_service.run_backup_cycle()` in a thread executor, replies with snapshot name and pruned count
- Scheduled backup in `services/scheduler.py` — `run_backup_cycle()` runs unconditionally on every weekly maintenance cycle, after maintenance and dedup passes
- `close_client()` in `db/vectors.py` — safely closes the Qdrant singleton before file copy to avoid Windows file-lock conflicts; client re-initializes lazily on next use
- `LEARN_BACKUP_DIR` env var (`config.py`) — overrides the backup output directory (default: `backups/` inside the project root)
- `LEARN_BACKUP_RETENTION_DAYS` env var (`config.py`) — sets snapshot retention window in days (default: `7`, minimum: `1`)
- `format_quiz_metadata(concept)` in `services/formatting.py` — returns a compact metadata footer (`📖 **Title** · Score: N/100 · Review #N`) appended to all quiz question messages; includes a skip-unlock hint when `review_count < 2`
- Quiz question messages now show concept title, mastery score, and review count on every delivery (scheduled DM, `/review`, `/learn`, button-triggered quiz)
- `pytest-xdist[psutil]>=3.0` to `requirements-dev.txt` — enables the default parallel pytest configuration (`-n 4 --dist loadfile` via `pyproject.toml`)
- `make test-fast` target in `Makefile` — runs the `unit`-marked subset for faster local feedback
- `tests/test_messages.py` — unit tests for `send_long_with_view` kwarg-omission behavior (`test_send_long_with_view_omits_view_kwarg_when_none`, `test_send_long_with_view_passes_view_kwarg_when_provided`)
- `is_quiz_active()` helper in `services/pipeline.py` — single source of truth for whether a quiz session is currently active (checks `quiz_anchor_concept_id` and `active_concept_ids` session keys)
- `_CONFIRMABLE_ACTIONS` whitelist in `/api/chat/confirm`; the endpoint now returns HTTP 400 for any action type not in the whitelist (`add_concept`, `suggest_topic`, `add_topic`, `link_concept`)
- 9 new tests in `tests/test_assess_no_quiz_guard.py` covering the assess-guard behavior
- `LOG_LEVEL` env var in `.env` — controls log verbosity for `bot.py` (default: `INFO`; set to `DEBUG` to enable `[quiz_anchor]` and pipeline trace logs)
- `[quiz_anchor]` debug log lines in `services/context.py` (staleness check), `services/tools_assess.py` (anchor SET), and `services/pipeline.py` (anchor CLEAR + blocked-assess detail); visible when `LOG_LEVEL=DEBUG`
- `/reorganize` slash command in `bot/commands.py` — manually triggers the taxonomy reorganization agent for the authorized user
- `/preference` slash command in `bot/commands.py` — no-arg mode displays the runtime `data/preferences.md`; text mode routes through an isolated LLM edit flow and shows Apply/Reject buttons before writing the file
- `PreferenceUpdateView` in `services/views.py` — confirmation UI for applying or rejecting proposed preference edits
- `data/skills/preferences.md` — dedicated skill file for the isolated `preference-edit` mode
- `SKILL_SETS["preference-edit"]` plus `call_preference_edit()` / `execute_preference_update()` in `services/pipeline.py` — fenced-output edit flow that bypasses normal conversation-history injection
- `data/preferences.template.md` — tracked default preferences file; runtime `data/preferences.md` is now git-ignored and auto-copied from the template during bot startup
- `PREFERENCES_TEMPLATE_MD` in `config.py` and startup bootstrap in `bot/events.py` — ensures first-run creation of a local runtime preferences file
- `data/skills/taxonomy.md` — LLM skill file for the taxonomy reorganization agent; covers topic tree restructuring, grouping rules, rename criteria, and suppressed-rename handling
- `SKILL_SETS["taxonomy"]` in `services/pipeline.py` — new `"taxonomy-mode"` skill set (`taxonomy` only); entry points `handle_taxonomy()` and `call_taxonomy_loop()`
- `call_action_loop()` in `services/pipeline.py` — generic LLM action loop shared by maintenance and taxonomy; `call_maintenance_loop()` and `call_taxonomy_loop()` are thin wrappers around it
- `build_taxonomy_context()` in `services/context.py` — builds DFS topic tree + suppressed renames context for the taxonomy agent
- `get_rejected_renames(days=90)` in `db/action_log.py` — suppresses re-proposed renames the user already rejected
- `SAFE_TAXONOMY_ACTIONS` in `services/pipeline.py` — `frozenset({"add_topic", "link_topics", "fetch", "list_topics"})`; `unlink_topics` intentionally excluded
- `add_topic` added to `SAFE_MAINTENANCE_ACTIONS` in `services/pipeline.py`
- `_check_taxonomy()` in `services/scheduler.py` — runs taxonomy reorganization in the weekly cycle after `_check_maintenance()`
- `_send_mode_report()` in `services/scheduler.py` — shared DM dispatcher used by both maintenance and taxonomy
- `ProposedActionsView` in `services/views.py` — renamed from `MaintenanceConfirmView`; now shared by both maintenance and taxonomy approval flows
- `CHANGELOG.md` — this file
- `Makefile` — common developer commands
- `requirements-dev.txt` — development/test/lint dependencies separated from runtime
- `docs/API.md` — overview of all API surfaces (Discord bot, FastAPI, Web UI)
- `docs/SETUP.md` — detailed local-development setup guide
- Expanded `pyproject.toml` with Ruff and pytest configuration
- `.github/workflows/lint.yml` — Ruff lint CI job

### Fixed
- `services/backup.py` — temp backup directory promotion now retries on transient Windows `PermissionError` file locks (common with OneDrive/Defender on freshly copied vector-store files) before failing the backup
- Missing `QuizQuestionView` import in `bot/commands.py` (caused a `NameError` on skip-eligible `/learn` quiz deliveries)
- Quiz deliveries via typed message (`on_message`) with `show_skip=False` fell through to `send_long_with_view` without metadata; guard widened from `elif quiz_meta and quiz_meta.get('show_skip'):` to `elif quiz_meta:` in both `bot/commands.py` and `bot/events.py`
- `send_long_with_view()` (`bot/messages.py`) omits the `view=` kwarg entirely when `view` is `None`; Discord raises `TypeError` when `view=None` is passed explicitly
- `assess` and `multi_assess` actions are now blocked when no quiz is active; `execute_action` in `pipeline.py` and `scripts/agent.py` returns a `REPLY:` message instead of mutating scores or logs
- `/review` command now pre-sets `quiz_anchor_concept_id` before executing the LLM response, preventing anchor loss on the first assess turn
- Test isolation: `db.chat.CHAT_DB` is now patched in `tests/conftest.py` alongside `db.core.CHAT_DB`, fixing leakage between test cases
- `_is_quiz_stale()` (`services/context.py`) compared `datetime.now()` (local time) against SQLite `CURRENT_TIMESTAMP` (UTC); in UTC+8 this caused every quiz to appear ~8 hours stale immediately after creation, clearing the quiz anchor and blocking all `assess` actions — fixed by switching to `datetime.now(timezone.utc).replace(tzinfo=None)`

### Changed
- `MAINTENANCE_INTERVAL_HOURS` changed from `24` to `168` — maintenance, taxonomy, dedup, and backup now run on a weekly schedule instead of daily
- `.github/workflows/tests.yml` — installs dev dependencies from `requirements-dev.txt`
- `docs/index.md` — updated to reference new documentation files

### Refactored
- Extracted `db/migrations.py` (~265 lines) from `db/core.py` — all schema migration blocks
- Extracted `webui/helpers.py` (~145 lines) and `webui/pages.py` (~890 lines) from `webui/server.py`
- Extracted `services/tools_assess.py` (~360 lines) from `services/tools.py` — quiz/assess action handlers
- Updated all documentation to reflect new module structure

---

## [0.1.0] — Initial release

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
