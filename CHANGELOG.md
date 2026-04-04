# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `CHANGELOG.md` — this file
- `Makefile` — common developer commands
- `requirements-dev.txt` — development/test/lint dependencies separated from runtime
- `docs/API.md` — overview of all API surfaces (Discord bot, FastAPI, Web UI)
- `docs/SETUP.md` — detailed local-development setup guide
- Expanded `pyproject.toml` with Ruff and pytest configuration
- `.github/workflows/lint.yml` — Ruff lint CI job

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
