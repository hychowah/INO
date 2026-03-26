.PHONY: test lint format run-bot run-api

# Run the test suite
test:
	pytest tests/ -v --tb=short

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
	uvicorn api:app --reload --host 0.0.0.0 --port 8000
