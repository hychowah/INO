"""FastAPI application factory — creates and configures the ``app`` instance."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from services import pipeline, scheduler

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases on startup."""
    del app
    pipeline.init_databases()
    scheduler.start(owner_label="api")
    logger.info("API started — databases initialized")
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(
    title="Learning Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
frontend_assets = FRONTEND_DIST / "assets"
if frontend_assets.exists():
    app.mount("/assets", StaticFiles(directory=frontend_assets.resolve()), name="assets")

# Register all route modules
from api import routes as _routes  # noqa: E402

_routes.register_routes(app)
