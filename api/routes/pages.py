"""SPA page routes served by FastAPI."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(include_in_schema=False)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _frontend_missing_response() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
            <head>
                <meta charset="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>Frontend Build Missing</title>
            </head>
            <body>
                <main>
                    <h1>Frontend bundle not built</h1>
                    <p>Build the React frontend before opening browser routes.</p>
                    <p>Run <code>make build-ui</code> from the repository root.</p>
                </main>
            </body>
        </html>
        """.strip()
    )


def _spa_entry_response() -> FileResponse | HTMLResponse:
    spa_entry = FRONTEND_DIST / "index.html"
    if spa_entry.exists():
        return FileResponse(spa_entry)
    return _frontend_missing_response()


@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    return _spa_entry_response()


@router.get("/chat", response_class=HTMLResponse)
async def chat_page():
    return _spa_entry_response()


@router.get("/topics", response_class=HTMLResponse)
async def topics_page():
    return _spa_entry_response()


@router.get("/topic/{topic_id}", response_class=HTMLResponse)
async def topic_detail_page(topic_id: int):
    return _spa_entry_response()


@router.get("/concepts", response_class=HTMLResponse)
async def concepts_page():
    return _spa_entry_response()


@router.get("/concept/{concept_id}", response_class=HTMLResponse)
async def concept_detail_page(concept_id: int):
    return _spa_entry_response()


@router.get("/graph", response_class=HTMLResponse)
async def graph_page():
    return _spa_entry_response()


@router.get("/reviews", response_class=HTMLResponse)
async def reviews_page():
    return _spa_entry_response()


@router.get("/forecast", response_class=HTMLResponse)
async def forecast_page():
    return _spa_entry_response()


@router.get("/actions", response_class=HTMLResponse)
async def actions_page():
    return _spa_entry_response()
