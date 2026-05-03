"""Tests for SPA page routes in api.routes.pages."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

import config
import db
from api import app


@pytest.fixture(autouse=True)
def _no_auth():
    """Disable auth for page-route tests by default."""
    with patch.object(config, "API_SECRET_KEY", ""):
        yield


@pytest.fixture
async def client(test_db):
    """Async HTTP client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _assert_missing_frontend(resp):
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Frontend bundle not built" in resp.text
    assert "make build-ui" in resp.text


def _topic_detail_path():
    topic_id = db.add_topic("Operating Systems")
    return f"/topic/{topic_id}"


def _concept_detail_path():
    concept_id = db.add_concept("Rust Ownership")
    return f"/concept/{concept_id}"


PAGE_CASES = [
    ("/", "react dashboard", "dashboard"),
    ("/chat", "react chat", "chat"),
    (_topic_detail_path, "react topic detail", "topic-detail"),
    (_concept_detail_path, "react concept detail", "concept-detail"),
    ("/actions", "react actions", "actions"),
    ("/knowledge", "react knowledge", "knowledge"),
    ("/knowledge/concepts", "react concepts", "knowledge-concepts"),
    ("/knowledge/graph", "react graph", "knowledge-graph"),
    ("/progress", "react reviews", "progress"),
    ("/progress/forecast", "react forecast", "progress-forecast"),
]


def _resolve_path(route_or_factory):
    return route_or_factory() if callable(route_or_factory) else route_or_factory


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("route_or_factory", "root_text", "case_id"),
    PAGE_CASES,
    ids=[case[2] for case in PAGE_CASES],
)
async def test_spa_routes_return_missing_frontend_placeholder(
    client, tmp_path, route_or_factory, root_text, case_id
):
    del root_text, case_id
    route = _resolve_path(route_or_factory)

    with patch("api.routes.pages.FRONTEND_DIST", tmp_path / "missing-dist"):
        resp = await client.get(route)

    _assert_missing_frontend(resp)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("route_or_factory", "root_text", "case_id"),
    PAGE_CASES,
    ids=[case[2] for case in PAGE_CASES],
)
async def test_spa_routes_serve_built_frontend_when_present(
    client, tmp_path, route_or_factory, root_text, case_id
):
    del case_id
    route = _resolve_path(route_or_factory)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text(
        f'<html><body><div id="root">{root_text}</div></body></html>',
        encoding="utf-8",
    )

    with patch("api.routes.pages.FRONTEND_DIST", dist_dir):
        resp = await client.get(route)

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert f'<div id="root">{root_text}</div>' in resp.text


@pytest.mark.anyio
async def test_actions_page_ignores_query_string_without_built_frontend(client, tmp_path):
    with patch("api.routes.pages.FRONTEND_DIST", tmp_path / "missing-dist"):
        resp = await client.get("/actions?action=assess&source=api&q=rust&time=7d&page=2")

    _assert_missing_frontend(resp)


@pytest.mark.anyio
async def test_static_style_not_served_by_fastapi(client):
    resp = await client.get("/static/style.css")

    assert resp.status_code == 404


@pytest.mark.anyio
async def test_forecast_json_endpoint_served_by_fastapi(client):
    resp = await client.get("/api/forecast?range=weeks")

    assert resp.status_code == 200
    data = resp.json()
    assert "overdue_count" in data
    assert "buckets" in data
