"""Legacy HTML page routes served by FastAPI during the webui transition."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from webui.pages import (
    page_actions,
    page_chat,
    page_concept_detail,
    page_concepts,
    page_dashboard,
    page_forecast,
    page_graph,
    page_reviews,
    page_topic_detail,
    page_topics,
)

router = APIRouter(include_in_schema=False)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _spa_entry_response() -> FileResponse | None:
    spa_entry = FRONTEND_DIST / "index.html"
    if spa_entry.exists():
        return FileResponse(spa_entry)
    return None


@router.get("/", response_class=HTMLResponse)
async def dashboard_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_dashboard()


@router.get("/chat", response_class=HTMLResponse)
async def chat_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_chat()


@router.get("/topics", response_class=HTMLResponse)
async def topics_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_topics()


@router.get("/topic/{topic_id}", response_class=HTMLResponse)
async def topic_detail_page(topic_id: int):
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_topic_detail(topic_id)


@router.get("/concepts", response_class=HTMLResponse)
async def concepts_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_concepts()


@router.get("/concept/{concept_id}", response_class=HTMLResponse)
async def concept_detail_page(concept_id: int):
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_concept_detail(concept_id)


@router.get("/graph", response_class=HTMLResponse)
async def graph_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_graph()


@router.get("/reviews", response_class=HTMLResponse)
async def reviews_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_reviews()


@router.get("/forecast", response_class=HTMLResponse)
async def forecast_page():
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_forecast()


@router.get("/actions", response_class=HTMLResponse)
async def actions_page(request: Request):
    spa_response = _spa_entry_response()
    if spa_response is not None:
        return spa_response
    return page_actions(str(request.url.query))