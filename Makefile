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
	python -c "import config, uvicorn; uvicorn.run('api:app', host=config.API_HOST, port=config.API_PORT, reload=True)"
