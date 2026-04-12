.PHONY: test test-fast test-all test-ui test-e2e lint format run-bot run-api dev-ui build-ui dev-all

# Run the full test suite (parallel)
test: test-all

# Run only pure unit tests (fast feedback, no DB or network)
test-fast:
	python -c "import os, subprocess, sys; env=os.environ.copy(); env.setdefault('LEARN_LLM_PROVIDER', 'kimi'); env.setdefault('LEARN_AUTHORIZED_USER_ID', '123456789'); raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-m', 'unit'], env=env))"

# Run the full test suite
test-all:
	python -c "import os, subprocess, sys; env=os.environ.copy(); env.setdefault('LEARN_LLM_PROVIDER', 'kimi'); env.setdefault('LEARN_AUTHORIZED_USER_ID', '123456789'); raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', 'tests/'], env=env))"

# Run the React chat frontend tests
test-ui:
	cd frontend && npm run test

# Run browser E2E smoke tests for the React frontend
test-e2e:
	cd frontend && npm run test:e2e

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

# Start the Vite chat frontend (requires npm install in frontend/ first)
dev-ui:
	cd frontend && npm run dev

# Start API + frontend dev server + Discord bot together
dev-all:
	python scripts/dev_all.py

# Build the React chat frontend for FastAPI to serve
build-ui:
	cd frontend && npm run build
