# Contributing to Learning Agent

Thank you for your interest in contributing! This guide covers local setup, testing, linting, and the pull request workflow.

## Prerequisites

- Python 3.10 or later
- `git`

## Local Setup

```bash
# 1. Fork and clone the repository
git clone https://github.com/<your-username>/INO.git
cd INO

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate          # Linux / macOS
venv\Scripts\activate             # Windows (cmd)
.\venv\Scripts\Activate.ps1       # Windows (PowerShell)

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Install development dependencies (pytest, ruff, …)
pip install -r requirements-dev.txt

# 5. Configure environment variables
cp .env.example .env
# Edit .env and fill in the required values
```

See [docs/SETUP.md](docs/SETUP.md) for a detailed walkthrough including optional Qdrant setup.

## Running the Tests

```bash
# Run the full test suite
make test

# Or directly with pytest
pytest tests/ -v --tb=short
```

Tests require the following environment variables (safe dummy values work for the unit tests):

```
LEARN_LLM_PROVIDER=kimi
LEARN_AUTHORIZED_USER_ID=123456789
```

These are set automatically when using `make test`.

## Linting and Formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting.

```bash
# Check for lint errors
make lint

# Auto-format the codebase
make format
```

Both commands can also be run directly:

```bash
ruff check .
ruff format .
```

Ruff is configured in `pyproject.toml` under `[tool.ruff]`.

## Running the Application

```bash
# Start the Discord bot
make run-bot

# Start the FastAPI backend
make run-api
```

See [docs/SETUP.md](docs/SETUP.md) for full startup instructions and environment variable reference.

## Pull Request Workflow

1. Create a feature branch from `master`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. Make your changes, keeping commits focused and descriptive.

3. Ensure tests pass and no lint errors exist:
   ```bash
   make lint
   make test
   ```

4. Push your branch and open a Pull Request against `master`.

5. Fill in the PR description explaining *what* changed and *why*.

6. At least one approval is required before merging.

## Branch Naming

| Type | Pattern | Example |
|------|---------|---------|
| Feature | `feat/<description>` | `feat/add-quiz-export` |
| Bug fix | `fix/<description>` | `fix/score-overflow` |
| Chore / docs | `chore/<description>` | `chore/update-deps` |
| Refactor | `refactor/<description>` | `refactor/split-bot-cogs` |

## Commit Message Style

Use the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
feat: add quiz export command
fix: prevent score overflow on rapid answers
docs: add API.md overview
chore: upgrade ruff to 0.4
```

## Reporting Bugs

Open a GitHub issue with:
- A clear title and description
- Steps to reproduce
- Expected vs. actual behaviour
- Python version and OS

## Code Style

- Follow existing patterns in the file you are editing.
- Keep lines to 100 characters or fewer.
- Add docstrings to new public functions/classes where they aid understanding.
- Do not move or restructure runtime code in documentation-only PRs.

## Future Refactor Targets (documented, not yet done)

The following are planned for later PRs — **please do not include these in unrelated PRs**:

- Split `bot.py` into `cogs/` (discord.py Cog pattern)
- Split `api.py` into `routers/` (FastAPI APIRouter pattern)
- Split `services/tools.py`, `services/pipeline.py`, `services/context.py`
- Split `webui/server.py` into route handlers
- Move `scripts/test_quiz_generator.py` and `scripts/test_similarity.py` to `tests/`
- Organise `tests/` into `unit/` and `integration/` subdirectories
