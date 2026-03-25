.PHONY: test lint format run-bot run-api

# Run the test suite
test:
	LEARN_LLM_PROVIDER=kimi LEARN_AUTHORIZED_USER_ID=123456789 \
	pytest tests/ -v --tb=short

# Lint with Ruff
lint:
	ruff check .

# Format with Ruff
format:
	ruff format .

# Start the Discord bot
run-bot:
	python bot.py

# Start the FastAPI backend (with live-reload)
run-api:
	uvicorn api:app --reload --host 0.0.0.0 --port 8000
