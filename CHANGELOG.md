# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `pytest-xdist[psutil]>=3.0` to `requirements-dev.txt` — enables parallel test execution (`pytest -n auto`); opt-in only, not added to `addopts` in `pyproject.toml`
- `tests/test_messages.py` — unit tests for `send_long_with_view` kwarg-omission behavior (`test_send_long_with_view_omits_view_kwarg_when_none`, `test_send_long_with_view_passes_view_kwarg_when_provided`)
- `is_quiz_active()` helper in `services/pipeline.py` — single source of truth for whether a quiz session is currently active (checks `quiz_anchor_concept_id` and `active_concept_ids` session keys)
- `_CONFIRMABLE_ACTIONS` whitelist in `/api/chat/confirm`; the endpoint now returns HTTP 400 for any action type not in the whitelist (`add_concept`, `suggest_topic`, `add_topic`, `link_concept`)
- 9 new tests in `tests/test_assess_no_quiz_guard.py` covering the assess-guard behavior
- `CHANGELOG.md` — this file
- `Makefile` — common developer commands
- `requirements-dev.txt` — development/test/lint dependencies separated from runtime
- `docs/API.md` — overview of all API surfaces (Discord bot, FastAPI, Web UI)
- `docs/SETUP.md` — detailed local-development setup guide
- Expanded `pyproject.toml` with Ruff and pytest configuration
- `.github/workflows/lint.yml` — Ruff lint CI job

### Fixed
- `send_long_with_view()` (`bot/messages.py`) omits the `view=` kwarg entirely when `view` is `None`; Discord raises `TypeError` when `view=None` is passed explicitly
- `assess` and `multi_assess` actions are now blocked when no quiz is active; `execute_action` in `pipeline.py` and `scripts/agent.py` returns a `REPLY:` message instead of mutating scores or logs
- `/review` command now pre-sets `quiz_anchor_concept_id` before executing the LLM response, preventing anchor loss on the first assess turn
- Test isolation: `db.chat.CHAT_DB` is now patched in `tests/conftest.py` alongside `db.core.CHAT_DB`, fixing leakage between test cases

### Changed
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
