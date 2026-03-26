"""FastAPI backend package for the Learning Agent."""

from api.app import app  # noqa: F401 — re-export for ``uvicorn api:app``

__all__ = ["app"]
