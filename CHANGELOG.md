# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `CHANGELOG.md` — this file
- `CONTRIBUTING.md` — contributor setup and workflow guide
- `Makefile` — common developer commands
- `requirements-dev.txt` — development/test/lint dependencies separated from runtime
- `docs/API.md` — overview of all API surfaces (Discord bot, FastAPI, Web UI)
- `docs/SETUP.md` — detailed local-development setup guide
- Expanded `pyproject.toml` with Ruff and pytest configuration
- `.github/workflows/lint.yml` — Ruff lint CI job

### Changed
- `.github/workflows/tests.yml` — installs dev dependencies from `requirements-dev.txt`
- `docs/index.md` — updated to reference new documentation files

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
