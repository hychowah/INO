# Changelog — Learning Agent

Key changes, newest first.

---

## May 2026

### Added

- **Chat flow harness** — added `scripts/test_chat_flow.py` plus `docs/CHAT_FLOW_HARNESS.md` for sandboxed, transcript-backed multi-turn conversation testing against the real chat pipeline

### Changed

- **Local-first runtime identity boundary** — Discord, API, browser, and scheduler flows now resolve through the canonical `LEARN_LOCAL_USER_ID`; FastAPI request scope may still override that alias with `X-Learning-User`
- **Typed chat envelope contract** — FastAPI chat endpoints now return an explicit `ChatResponse` shape with unset optional fields omitted on the wire, reducing browser/API contract drift without adding a new DTO layer
- **Active quiz follow-up routing** — interactive turns now switch to `REPLY` mode automatically when single-quiz, multi-quiz, or pending scheduled-review state is active, so follow-up quiz answers use the quiz-intent rules instead of the new-question path

### Refactored

- **Shared chat entry ownership** — FastAPI chat, confirm, decline, and structured chat-action flows now serialize inside `services/chat_session.py`; interactive turn setup is centralized in `services/state.begin_interactive_turn()` instead of duplicated across adapters
- **Lightweight approval parity** — `add_concept` and `suggest_topic` confirmation/decline side effects are now shared in `services/chat_actions.py` across browser/API chat, Discord views, and reply-based Discord confirms
- **Scheduler review-policy narrowing** — canonical single-concept review payload construction now lives in `services/pipeline.py`, while reminder cooldown/expiry decisions moved into `services/review_state.py`
- **Typed-only reminder state** — `scheduled_review_reminders` is now the only durable active-review state; the legacy `pending_review` compatibility bridge is retired from delivery, prompt-context, resend, and late-answer recovery paths
- **Shared Discord proposal execution** — Discord proposal buttons and slash `/maintain` plus `/reorganize` now delegate to the shared chat controller and shared chat-action dispatcher instead of owning duplicate workflow execution

### Fixed

- **Scoped provider session leakage** — runtime provider conversation sessions are now keyed by current user instead of one process-global cache
- **Browser/API skip user mismatch** — the shared `skip_quiz` action path now uses the current scoped user rather than the adapter display author
- **Plain Discord message user-scope mismatch** — ordinary `on_message` replies now use the same `LEARN_LOCAL_USER_ID` scope as scheduler and slash-command review state, preventing live review answers from missing their active quiz context
- **Immediate review-question prompt context** — active single-concept quiz context now includes the exact stored question from `last_quiz_question` before falling back to typed reminder state, making terse follow-up answers interpretable during the first response turn
- **Open-response review choices normalization** — shared review generation now treats quiz-generator payloads with `choices: null` as no multiple-choice options instead of crashing the `/review` flow with `TypeError: 'NoneType' object is not iterable`
- **Old-database bootstrap safety** — user-id-dependent indexes are now created after migrations in `db/core.py`, so copied or upgraded older databases can boot cleanly during migration rehearsal
- **Proactive reminder self-healing** — scheduler review checks now clear malformed or deleted legacy `pending_review` state before importing it into `scheduled_review_reminders`, so one stale reminder blob no longer aborts proactive Discord review delivery while manual `/review` still works
- **Legacy reminder bridge recovery** — when only the compatibility `pending_review` mirror exists, the next scheduler pass can re-import it into the typed reminder row after validating concept existence and normalizing timestamps
- **Skip-button re-arming on fresh reviews** — each newly delivered review question now resets the stale `quiz_answered` guard before sending the message, so `I know this` works on the next eligible question instead of incorrectly reporting the quiz was already answered or skipped

## April 2026

### Added

- **Desktop-first browser shell redesign** — the React frontend now uses a nested `AppShell` with Dashboard, Chat, Knowledge, and Progress as the primary surfaces; legacy `/topics`, `/concepts`, `/graph`, `/reviews`, and `/forecast` paths are preserved as compatibility redirects inside the SPA
- **Knowledge consolidation** — Topics, Concepts, and Graph now live under `/knowledge`, with inline Topic and Concept detail panels, compatibility drill-in routes (`/topic/{id}`, `/concept/{id}`), and resizable split panels for embedded detail workflows
- **Progress consolidation** — Reviews and Forecast now live under `/progress` and `/progress/forecast`; old standalone forecast/reviews pages were removed after the consolidated surface landed
- **Shell utilities** — Activity now opens as a drawer in normal shell flow while `/actions` remains as a compatibility route; a `cmdk`-based command palette is available from the shell and opens with `Ctrl+K`

### Changed

- **LLM output-contract hardening** — main interactive LLM calls now validate raw provider output before execution/history/display, can request structured output via `LEARN_LLM_OUTPUT_MODE=auto|json_object|json_schema|legacy`, retry once without `response_format` on incompatible endpoints, log malformed completions privately under `data/llm_failures/`, and expose a manual real-provider validator via `scripts/live_output_contract_smoke.py`
- **Persisted shared scheduler** — review delivery stays bot-owned, while taxonomy, backup, proposal cleanup, and optional maintenance/dedup jobs now run on independent wall-clock cadences coordinated through a DB-backed owner lock shared by `bot.py` and `api.py`
- **Background feature defaults** — maintenance and dedup are now disabled by default behind `LEARN_ENABLE_MAINTENANCE=0` and `LEARN_ENABLE_DEDUP=0`; `/maintain` remains available as a gated operator command when re-enabled
- **Automatic backup cadence** — backups now run independently every 24 hours by default, use the newest valid backup directory on disk as the due-check source of truth, and retain 14 days of snapshots by default
- **CI and test-suite maintenance** — `.github/workflows/tests.yml` now performs a `pytest --collect-only tests/` guard before the Python matrix run; docs and test inventory were refreshed to match the current split API/page/tool/quiz test layout and the manual `scripts/maintenance_smoke.py` path
- **FastAPI SPA serving** — the backend no longer serves only an explicit allowlist of page routes; it now serves the built SPA for HTML requests outside the reserved prefixes `/api`, `/assets`, and `/static`
- **Vite dev behavior** — the frontend dev server now proxies only `/api`, `/assets`, and `/static`; client-side browser routes stay inside the SPA
- **Frontend documentation** — README, API, setup, architecture, dev notes, and docs index were refreshed to reflect the consolidated Knowledge/Progress surfaces, Activity drawer, command palette, and resizable Knowledge panels

### Removed

- **Legacy `webui/` runtime** — the separate Python-rendered browser stack and companion `8050` flow have been retired; FastAPI now serves the built React SPA through its HTML fallback route, and browser chat uses the shared FastAPI chat controller with buffered SSE replay via `/api/chat/stream`

### Added

- **Taxonomy shadow rebuild** (`scripts/taxonomy_shadow_rebuild.py`, `docs/TAXONOMY_REBUILD.md`) — operator workflow that previews taxonomy changes against shadow copies of the live DBs/vector store, records replayable safe actions, writes before/after structure snapshots, and replays safe actions against live data after a backup; driven by `call_taxonomy_loop()` with `max_actions`, `action_journal`, and `operator_directive` hooks
- **Backup service** (`services/backup.py`, `/backup` slash command) — snapshots `knowledge.db`, `chat_history.db`, and `data/vectors/` into a timestamped directory; prunes snapshots older than `LEARN_BACKUP_RETENTION_DAYS` (default: 14); runs on its own scheduler cadence; on-demand via `/backup`
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
