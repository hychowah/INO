.PHONY: test test-fast test-all lint format run-bot run-api

# Run the full test suite (parallel)
test: test-all

# Run only pure unit tests (fast feedback, no DB or network)
test-fast:
	python -c "import os, subprocess, sys; env=os.environ.copy(); env.setdefault('LEARN_LLM_PROVIDER', 'kimi'); env.setdefault('LEARN_AUTHORIZED_USER_ID', '123456789'); raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-m', 'unit'], env=env))"

# Run the full test suite
test-all:
	python -c "import os, subprocess, sys; env=os.environ.copy(); env.setdefault('LEARN_LLM_PROVIDER', 'kimi'); env.setdefault('LEARN_AUTHORIZED_USER_ID', '123456789'); raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', 'tests/'], env=env))"

# Lint with Ruff
lint:
	ruff check .
	ruff format --check .

# Format with Ruff
format:
	ruff format .

# Start the Discord bot
run-bot:
	python bot.py

# Start the FastAPI backend (with live-reload)
run-api:
	python -c "import config, uvicorn; uvicorn.run('api:app', host=config.API_HOST, port=config.API_PORT, reload=True)"
