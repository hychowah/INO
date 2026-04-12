"""
Tests for the FastAPI REST API (api.py).

Covers all CRUD endpoints: concepts, topics, relations, reviews, actions, graph.
Uses the shared test_db fixture for DB isolation and httpx AsyncClient for requests.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import config
import db
from api import app

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _no_auth():
    """Disable auth for all tests by default."""
    with patch.object(config, "API_SECRET_KEY", ""):
        yield


@pytest.fixture
async def client(test_db):
    """Async HTTP client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ============================================================================
# Helpers
# ============================================================================


def _make_topic(title="Test Topic", description=None, parent_ids=None):
    return db.add_topic(title=title, description=description, parent_ids=parent_ids)


def _make_concept(title="Test Concept", description=None, topic_id=None):
    topic_ids = [topic_id] if topic_id else None
    return db.add_concept(title=title, description=description, topic_ids=topic_ids)


# ============================================================================
# Chat
# ============================================================================


class TestChat:
    @pytest.mark.anyio
    async def test_chat_empty_message_400(self, client):
        resp = await client.post("/api/chat", json={"message": "   "})
        assert resp.status_code == 400
        assert "Message cannot be empty" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_chat_supports_webui_ping_command(self, client):
        resp = await client.post("/api/chat", json={"message": "/ping"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Pong!",
            "pending_action": None,
        }

    @pytest.mark.anyio
    async def test_chat_clear_exposes_clear_history_flag(self, client):
        db.add_chat_message("user", "hello")
        db.add_chat_message("assistant", "hi")

        resp = await client.post("/api/chat", json={"message": "/clear"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Chat history cleared.",
            "pending_action": None,
            "clear_history": True,
        }
        assert db.get_chat_history(limit=5) == []

    @pytest.mark.anyio
    async def test_chat_normal_reply(self, client):
        with (
            patch(
                "webui.chat_backend.pipeline.call_with_fetch_loop",
                new=AsyncMock(return_value="REPLY: raw"),
            ),
            patch("webui.chat_backend.parse_llm_response", return_value=("REPLY", "raw", None)),
            patch(
                "webui.chat_backend.pipeline.execute_llm_response",
                new=AsyncMock(return_value="REPLY: Final answer"),
            ),
        ):
            resp = await client.post("/api/chat", json={"message": "hello"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Final answer",
            "pending_action": None,
        }

    @pytest.mark.anyio
    async def test_chat_add_concept_returns_pending_confirm(self, client):
        action_data = {
            "action": "add_concept",
            "message": "Add this concept?",
            "params": {"title": "Rust", "topic_titles": ["Programming"]},
        }
        with (
            patch(
                "webui.chat_backend.pipeline.call_with_fetch_loop",
                new=AsyncMock(return_value="ignored"),
            ),
            patch(
                "webui.chat_backend.parse_llm_response",
                return_value=("FETCH", "Add this concept?", action_data),
            ),
        ):
            resp = await client.post("/api/chat", json={"message": "teach me rust"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "pending_confirm",
            "message": "Add this concept?",
            "pending_action": action_data,
        }
        history = db.get_chat_history(limit=5)
        assert history[-2]["role"] == "user"
        assert history[-2]["content"] == "teach me rust"
        assert history[-1]["role"] == "assistant"
        assert history[-1]["content"] == "Add this concept?"

    @pytest.mark.anyio
    async def test_chat_suggest_topic_returns_pending_confirm(self, client):
        action_data = {
            "action": "suggest_topic",
            "message": "Want me to add this topic?",
            "params": {"title": "Compilers"},
        }
        with (
            patch(
                "webui.chat_backend.pipeline.call_with_fetch_loop",
                new=AsyncMock(return_value="ignored"),
            ),
            patch(
                "webui.chat_backend.parse_llm_response",
                return_value=("FETCH", "Want me to add this topic?", action_data),
            ),
        ):
            resp = await client.post("/api/chat", json={"message": "I want to learn compilers"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "pending_confirm",
            "message": "Want me to add this topic?",
            "pending_action": action_data,
        }

    @pytest.mark.anyio
    async def test_confirm_whitelisted_action_succeeds(self, client):
        action_data = {
            "action": "add_concept",
            "message": "Add this concept?",
            "params": {"title": "Ownership"},
        }
        with patch("webui.chat_backend.execute_action", return_value=("reply", "Added concept #7")):
            resp = await client.post("/api/chat/confirm", json={"action_data": action_data})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Add this concept?\n\n✅ Added concept #7",
            "pending_action": None,
        }
        history = db.get_chat_history(limit=5)
        assert history[-2]["content"] == "[confirmed: add concept]"
        assert history[-1]["content"] == "✅ Added concept #7"

    @pytest.mark.anyio
    async def test_confirm_suggest_topic_uses_accept_flow(self, client):
        action_data = {
            "action": "suggest_topic",
            "message": "Want me to add this topic?",
            "params": {"title": "Compilers"},
        }
        with patch(
            "webui.chat_backend.execute_suggest_topic_accept",
            return_value=(True, "✅ Created topic **Compilers** (#3)", 3),
        ):
            resp = await client.post("/api/chat/confirm", json={"action_data": action_data})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Want me to add this topic?\n\n✅ Created topic **Compilers** (#3)",
            "pending_action": None,
        }
        history = db.get_chat_history(limit=5)
        assert history[-2]["content"] == '[confirmed: add topic "Compilers"]'
        assert history[-1]["content"] == "✅ Created topic **Compilers** (#3)"

    @pytest.mark.anyio
    async def test_confirm_non_whitelisted_action_400(self, client):
        resp = await client.post(
            "/api/chat/confirm",
            json={"action_data": {"action": "assess", "params": {"concept_id": 1}}},
        )
        assert resp.status_code == 400
        assert "cannot be confirmed" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_decline_add_concept_writes_user_history(self, client):
        resp = await client.post(
            "/api/chat/decline",
            json={"action_data": {"action": "add_concept", "params": {"title": "Borrow checker"}}},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Declined.",
            "pending_action": None,
        }
        history = db.get_chat_history(limit=5)
        assert history[-1]["role"] == "user"
        assert history[-1]["content"] == "[declined: add concept]"

    @pytest.mark.anyio
    async def test_decline_suggest_topic_writes_user_history(self, client):
        resp = await client.post(
            "/api/chat/decline",
            json={"action_data": {"action": "suggest_topic", "params": {"title": "Compilers"}}},
        )

        assert resp.status_code == 200
        history = db.get_chat_history(limit=5)
        assert history[-1]["role"] == "user"
        assert history[-1]["content"] == '[declined: add topic "Compilers"]'

    @pytest.mark.anyio
    async def test_decline_unknown_action_400(self, client):
        resp = await client.post(
            "/api/chat/decline",
            json={"action_data": {"action": "assess", "params": {"concept_id": 1}}},
        )
        assert resp.status_code == 400
        assert "cannot be declined" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_chat_401_missing_token_when_auth_enabled(self, test_db):
        with patch.object(config, "API_SECRET_KEY", "real-secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post("/api/chat", json={"message": "hello"})
                assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_chat_allows_local_webui_without_token_when_auth_enabled(self, test_db):
        with patch.object(config, "API_SECRET_KEY", "real-secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8050") as ac:
                resp = await ac.post("/api/chat", json={"message": "/ping"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Pong!",
            "pending_action": None,
        }

    @pytest.mark.anyio
    async def test_chat_allows_local_fastapi_ui_without_token_when_auth_enabled(self, test_db):
        with patch.object(config, "API_SECRET_KEY", "real-secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as ac:
                resp = await ac.post("/api/chat", json={"message": "/ping"})

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Pong!",
            "pending_action": None,
        }

    @pytest.mark.anyio
    async def test_chat_action_endpoint_dispatches_structured_action(self, client):
        with patch(
            "api.routes.chat.handle_webui_action",
            new=AsyncMock(
                return_value={
                    "type": "reply",
                    "message": "Next quiz",
                    "pending_action": None,
                    "actions": [
                        {
                            "type": "button_group",
                            "buttons": [
                                {
                                    "label": "Done",
                                    "style": "secondary",
                                    "action": {"kind": "dismiss"},
                                }
                            ],
                        }
                    ],
                }
            ),
        ):
            resp = await client.post(
                "/api/chat/action",
                json={"action": {"kind": "send_message", "message": "[BUTTON] Quiz me on the next due concept"}},
            )

        assert resp.status_code == 200
        assert resp.json() == {
            "type": "reply",
            "message": "Next quiz",
            "pending_action": None,
            "actions": [
                {
                    "type": "button_group",
                    "buttons": [
                        {
                            "label": "Done",
                            "style": "secondary",
                            "action": {"kind": "dismiss"},
                        }
                    ],
                }
            ],
        }

    @pytest.mark.anyio
    async def test_chat_bootstrap_returns_history_and_commands(self, client):
        db.add_chat_message("user", "hello")
        db.add_chat_message("assistant", "hi there")

        resp = await client.get("/api/chat/bootstrap")

        assert resp.status_code == 200
        data = resp.json()
        assert [entry["content"] for entry in data["history"]] == ["hello", "hi there"]
        assert data["commands"] == [
            {"label": "Review", "command": "/review"},
            {"label": "Due", "command": "/due"},
            {"label": "Topics", "command": "/topics"},
            {"label": "Maintain", "command": "/maintain"},
            {"label": "Reorganize", "command": "/reorganize"},
            {"label": "Preference", "command": "/preference "},
        ]


class TestLegacyPages:
    @pytest.mark.anyio
    async def test_chat_page_served_by_fastapi_without_built_frontend(self, client, tmp_path):
        with patch("api.routes.pages.FRONTEND_DIST", tmp_path / "missing-dist"):
            resp = await client.get("/chat")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert '<div class="chat-page">' in resp.text
        assert '/static/chat.js?v=2' in resp.text

    @pytest.mark.anyio
    async def test_chat_page_serves_built_frontend_when_present(self, client, tmp_path):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html><body><div id=\"root\">react chat</div></body></html>", encoding="utf-8")

        with patch("api.routes.pages.FRONTEND_DIST", dist_dir):
            resp = await client.get("/chat")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert '<div id="root">react chat</div>' in resp.text

    @pytest.mark.anyio
    async def test_static_style_served_by_fastapi(self, client):
        resp = await client.get("/static/style.css")

        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        assert ".chat-page" in resp.text

    @pytest.mark.anyio
    async def test_forecast_json_endpoint_served_by_fastapi(self, client):
        resp = await client.get("/api/forecast?range=weeks")

        assert resp.status_code == 200
        data = resp.json()
        assert "overdue_count" in data
        assert "buckets" in data

    @pytest.mark.anyio
    async def test_legacy_concept_delete_endpoint_served_by_fastapi(self, client):
        concept_id = _make_concept("Delete Me")

        resp = await client.post(f"/api/concept/{concept_id}/delete")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert db.get_concept(concept_id) is None


# ============================================================================
# Topic CRUD
# ============================================================================


class TestTopicCRUD:
    @pytest.mark.anyio
    async def test_get_topics_empty(self, client):
        resp = await client.get("/api/topics")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.anyio
    async def test_get_topics_with_data(self, client):
        _make_topic("Physics")
        resp = await client.get("/api/topics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(t["title"] == "Physics" for t in data)

    @pytest.mark.anyio
    async def test_get_topic_detail(self, client):
        tid = _make_topic("Chemistry")
        resp = await client.get(f"/api/topics/{tid}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Chemistry"

    @pytest.mark.anyio
    async def test_get_topic_404(self, client):
        resp = await client.get("/api/topics/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_create_topic(self, client):
        resp = await client.post("/api/topics", json={"title": "Biology"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Biology"
        assert "id" in data

    @pytest.mark.anyio
    async def test_create_topic_with_parent(self, client):
        parent_id = _make_topic("Science")
        resp = await client.post(
            "/api/topics",
            json={
                "title": "Genetics",
                "parent_ids": [parent_id],
            },
        )
        assert resp.status_code == 201
        # Verify parent link
        detail = await client.get(f"/api/topics/{resp.json()['id']}")
        assert any(p["id"] == parent_id for p in detail.json()["parents"])

    @pytest.mark.anyio
    async def test_update_topic(self, client):
        tid = _make_topic("Old Title")
        resp = await client.put(f"/api/topics/{tid}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    @pytest.mark.anyio
    async def test_update_topic_404(self, client):
        resp = await client.put("/api/topics/9999", json={"title": "X"})
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_topic(self, client):
        tid = _make_topic("To Delete")
        resp = await client.delete(f"/api/topics/{tid}")
        assert resp.status_code == 200
        # Verify gone
        resp2 = await client.get(f"/api/topics/{tid}")
        assert resp2.status_code == 404

    @pytest.mark.anyio
    async def test_delete_topic_404(self, client):
        resp = await client.delete("/api/topics/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_topic_with_concepts_409(self, client):
        """Deleting a topic that still has concepts returns 409."""
        tid = _make_topic("Has Concepts")
        cid = db.add_concept("Linked Concept", "desc")
        db.link_concept(cid, [tid])
        resp = await client.delete(f"/api/topics/{tid}")
        assert resp.status_code == 409
        assert "concept(s)" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_delete_topic_with_concepts_force(self, client):
        """Deleting a non-empty topic with ?force=true succeeds."""
        tid = _make_topic("Force Delete")
        cid = db.add_concept("Linked Concept", "desc")
        db.link_concept(cid, [tid])
        resp = await client.delete(f"/api/topics/{tid}?force=true")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_link_topics(self, client):
        p = _make_topic("Parent")
        c = _make_topic("Child")
        resp = await client.post(
            "/api/topics/link",
            json={
                "parent_id": p,
                "child_id": c,
            },
        )
        assert resp.status_code == 200
        assert "Linked" in resp.json()["message"]

    @pytest.mark.anyio
    async def test_link_topics_self_link(self, client):
        tid = _make_topic("Solo")
        resp = await client.post(
            "/api/topics/link",
            json={
                "parent_id": tid,
                "child_id": tid,
            },
        )
        assert resp.status_code == 400
        assert "itself" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_link_topics_cycle(self, client):
        a = _make_topic("A")
        b = _make_topic("B")
        db.link_topics(a, b)
        resp = await client.post(
            "/api/topics/link",
            json={
                "parent_id": b,
                "child_id": a,
            },
        )
        assert resp.status_code == 400
        assert "Cycle" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_link_topics_idempotent(self, client):
        p = _make_topic("P")
        c = _make_topic("C")
        db.link_topics(p, c)
        resp = await client.post(
            "/api/topics/link",
            json={
                "parent_id": p,
                "child_id": c,
            },
        )
        # Should return 200 "Already linked" not an error
        assert resp.status_code == 200
        assert "Already" in resp.json()["message"]

    @pytest.mark.anyio
    async def test_unlink_topics(self, client):
        p = _make_topic("P2")
        c = _make_topic("C2")
        db.link_topics(p, c)
        resp = await client.post(
            "/api/topics/unlink",
            json={
                "parent_id": p,
                "child_id": c,
            },
        )
        assert resp.status_code == 200
        assert "Unlinked" in resp.json()["message"]


# ============================================================================
# Concept CRUD
# ============================================================================


class TestConceptCRUD:
    @pytest.mark.anyio
    async def test_list_concepts_empty(self, client):
        resp = await client.get("/api/concepts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    @pytest.mark.anyio
    async def test_list_concepts_with_data(self, client):
        tid = _make_topic("T")
        _make_concept("Concept A", topic_id=tid)
        _make_concept("Concept B", topic_id=tid)
        resp = await client.get("/api/concepts")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.anyio
    async def test_list_concepts_filter_by_topic(self, client):
        t1 = _make_topic("T1")
        t2 = _make_topic("T2")
        _make_concept("In T1", topic_id=t1)
        _make_concept("In T2", topic_id=t2)
        resp = await client.get(f"/api/concepts?topic_id={t1}")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "In T1"

    @pytest.mark.anyio
    async def test_list_concepts_search(self, client):
        tid = _make_topic("T")
        _make_concept("Quantum Mechanics", topic_id=tid)
        _make_concept("Classical Mechanics", topic_id=tid)
        _make_concept("Thermodynamics", topic_id=tid)
        resp = await client.get("/api/concepts?search=Mechanics")
        data = resp.json()
        assert data["total"] >= 2
        titles = [i["title"] for i in data["items"]]
        assert "Quantum Mechanics" in titles
        assert "Classical Mechanics" in titles

    @pytest.mark.anyio
    async def test_list_concepts_pagination(self, client):
        tid = _make_topic("T")
        for i in range(5):
            _make_concept(f"Concept {i}", topic_id=tid)
        resp = await client.get("/api/concepts?page=1&per_page=2")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["per_page"] == 2

        resp2 = await client.get("/api/concepts?page=3&per_page=2")
        data2 = resp2.json()
        assert len(data2["items"]) == 1  # 5th item on page 3

    @pytest.mark.anyio
    async def test_get_concept_detail(self, client):
        tid = _make_topic("T")
        cid = _make_concept("Detail Test", topic_id=tid)
        resp = await client.get(f"/api/concepts/{cid}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Detail Test"

    @pytest.mark.anyio
    async def test_get_concept_404(self, client):
        resp = await client.get("/api/concepts/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_create_concept_with_topic_ids(self, client):
        tid = _make_topic("Host Topic")
        resp = await client.post(
            "/api/concepts",
            json={
                "title": "New Concept",
                "description": "Desc",
                "topic_ids": [tid],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "New Concept"
        assert "id" in data

        # Verify it's linked
        detail = await client.get(f"/api/concepts/{data['id']}")
        assert tid in detail.json().get("topic_ids", [])

    @pytest.mark.anyio
    async def test_create_concept_with_topic_titles(self, client):
        resp = await client.post(
            "/api/concepts",
            json={
                "title": "Auto-Topic Concept",
                "topic_titles": ["Brand New Topic"],
            },
        )
        assert resp.status_code == 201
        # The topic should have been auto-created
        concept = db.get_concept(resp.json()["id"])
        assert len(concept["topic_ids"]) == 1

    @pytest.mark.anyio
    async def test_create_concept_topic_titles_reuses_existing(self, client):
        existing_tid = _make_topic("Existing Topic")
        resp = await client.post(
            "/api/concepts",
            json={
                "title": "Reuse Topic Concept",
                "topic_titles": ["Existing Topic"],
            },
        )
        assert resp.status_code == 201
        concept = db.get_concept(resp.json()["id"])
        assert existing_tid in concept["topic_ids"]

    @pytest.mark.anyio
    async def test_create_concept_duplicate_409(self, client):
        _make_concept("Unique Title")
        resp = await client.post("/api/concepts", json={"title": "Unique Title"})
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_create_concept_missing_title_422(self, client):
        resp = await client.post("/api/concepts", json={"description": "no title"})
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_update_concept(self, client):
        cid = _make_concept("Old Name")
        resp = await client.put(f"/api/concepts/{cid}", json={"title": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Name"

    @pytest.mark.anyio
    async def test_update_concept_404(self, client):
        resp = await client.put("/api/concepts/9999", json={"title": "X"})
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_delete_concept(self, client):
        cid = _make_concept("To Delete")
        resp = await client.delete(f"/api/concepts/{cid}")
        assert resp.status_code == 200
        # Verify gone
        resp2 = await client.get(f"/api/concepts/{cid}")
        assert resp2.status_code == 404

    @pytest.mark.anyio
    async def test_delete_concept_404(self, client):
        resp = await client.delete("/api/concepts/9999")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_add_remark(self, client):
        cid = _make_concept("Remark Target")
        resp = await client.post(
            f"/api/concepts/{cid}/remarks",
            json={
                "content": "Remember this pattern",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["concept_id"] == cid
        assert data["content"] == "Remember this pattern"
        assert data["remark_summary"] == "Remember this pattern"

    @pytest.mark.anyio
    async def test_add_remark_404(self, client):
        resp = await client.post(
            "/api/concepts/9999/remarks",
            json={
                "content": "Ghost",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_add_remark_empty_content_422(self, client):
        cid = _make_concept("Remark Empty")
        resp = await client.post(f"/api/concepts/{cid}/remarks", json={"content": ""})
        assert resp.status_code == 422


# ============================================================================
# Relations
# ============================================================================


class TestRelations:
    @pytest.mark.anyio
    async def test_get_relations_empty(self, client):
        cid = _make_concept("Lonely")
        resp = await client.get(f"/api/concepts/{cid}/relations")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.anyio
    async def test_get_relations_with_data(self, client):
        a = _make_concept("Concept A")
        b = _make_concept("Concept B")
        db.add_relation(a, b, "builds_on")
        resp = await client.get(f"/api/concepts/{a}/relations")
        assert resp.status_code == 200
        rels = resp.json()
        assert len(rels) == 1
        assert rels[0]["other_concept_id"] == b

    @pytest.mark.anyio
    async def test_get_relations_404(self, client):
        resp = await client.get("/api/concepts/9999/relations")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_create_relation(self, client):
        a = _make_concept("Rel A")
        b = _make_concept("Rel B")
        resp = await client.post(
            "/api/relations",
            json={
                "concept_id_a": a,
                "concept_id_b": b,
                "relation_type": "contrasts_with",
            },
        )
        assert resp.status_code == 201
        assert "id" in resp.json()

    @pytest.mark.anyio
    async def test_create_relation_invalid_type(self, client):
        a = _make_concept("Bad Rel A")
        b = _make_concept("Bad Rel B")
        resp = await client.post(
            "/api/relations",
            json={
                "concept_id_a": a,
                "concept_id_b": b,
                "relation_type": "invalid_type",
            },
        )
        assert resp.status_code == 400
        assert "Invalid relation_type" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_create_relation_duplicate(self, client):
        a = _make_concept("Dup A")
        b = _make_concept("Dup B")
        db.add_relation(a, b, "builds_on")
        resp = await client.post(
            "/api/relations",
            json={
                "concept_id_a": a,
                "concept_id_b": b,
                "relation_type": "builds_on",
            },
        )
        assert resp.status_code == 400
        assert "rejected" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_create_relation_self_referential(self, client):
        a = _make_concept("Self Ref")
        resp = await client.post(
            "/api/relations",
            json={
                "concept_id_a": a,
                "concept_id_b": a,
                "relation_type": "builds_on",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_remove_relation(self, client):
        a = _make_concept("Rem A")
        b = _make_concept("Rem B")
        db.add_relation(a, b, "builds_on")
        resp = await client.post(
            "/api/relations/remove",
            json={
                "concept_id_a": a,
                "concept_id_b": b,
            },
        )
        assert resp.status_code == 200
        # Verify gone
        rels = db.get_relations(a)
        assert len(rels) == 0


# ============================================================================
# Reviews & Logs
# ============================================================================


class TestReviewsAndLogs:
    @pytest.mark.anyio
    async def test_get_reviews_requires_concept_id(self, client):
        resp = await client.get("/api/reviews")
        assert resp.status_code == 400
        assert "concept_id" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_get_reviews_with_concept_id(self, client):
        cid = _make_concept("Review Target")
        db.add_review(cid, "What is X?", "X is Y", 4, "Correct")
        resp = await client.get(f"/api/reviews?concept_id={cid}")
        assert resp.status_code == 200
        reviews = resp.json()
        assert len(reviews) == 1
        assert reviews[0]["question_asked"] == "What is X?"

    @pytest.mark.anyio
    async def test_get_next_review_no_concepts(self, client):
        resp = await client.get("/api/reviews/next")
        assert resp.status_code == 200
        assert resp.json() is None

    @pytest.mark.anyio
    async def test_get_next_review_with_due(self, client):
        cid = _make_concept("Due Concept")
        resp = await client.get("/api/reviews/next")
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["id"] == cid

    @pytest.mark.anyio
    async def test_get_actions_empty(self, client):
        resp = await client.get("/api/actions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.anyio
    async def test_get_actions_with_entries(self, client):
        db.log_action("assess", {"concept_id": 1}, "success", "done", source="api")
        db.log_action("quiz", {"concept_id": 2}, "success", "done", source="discord")
        resp = await client.get("/api/actions")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    @pytest.mark.anyio
    async def test_get_actions_filter_by_action(self, client):
        db.log_action("assess", {}, "success", "done")
        db.log_action("quiz", {}, "success", "done")
        resp = await client.get("/api/actions?action=assess")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["action"] == "assess"

    @pytest.mark.anyio
    async def test_get_actions_filter_by_source(self, client):
        db.log_action("assess", {}, "success", "done", source="api")
        db.log_action("quiz", {}, "success", "done", source="discord")
        resp = await client.get("/api/actions?source=api")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["source"] == "api"

    @pytest.mark.anyio
    async def test_get_actions_pagination(self, client):
        for i in range(5):
            db.log_action(f"action_{i}", {}, "success", "done")
        resp = await client.get("/api/actions?page=1&per_page=2")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1

        resp2 = await client.get("/api/actions?page=3&per_page=2")
        data2 = resp2.json()
        assert len(data2["items"]) == 1


# ============================================================================
# Graph
# ============================================================================


class TestGraph:
    @pytest.mark.anyio
    async def test_graph_empty(self, client):
        resp = await client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["concept_nodes"] == []
        assert data["topic_nodes"] == []
        assert data["concept_edges"] == []
        assert data["topic_edges"] == []

    @pytest.mark.anyio
    async def test_graph_with_data(self, client):
        tid = _make_topic("Graph Topic")
        a = _make_concept("Graph A", topic_id=tid)
        b = _make_concept("Graph B", topic_id=tid)
        db.add_relation(a, b, "builds_on")

        resp = await client.get("/api/graph")
        data = resp.json()
        assert len(data["concept_nodes"]) == 2
        assert len(data["topic_nodes"]) >= 1
        assert len(data["concept_edges"]) == 1


# ============================================================================
# Auth
# ============================================================================


class TestAuth:
    @pytest.mark.anyio
    async def test_401_with_wrong_token(self, test_db):
        """Verify auth rejection when a secret key is configured."""
        with patch.object(config, "API_SECRET_KEY", "real-secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/topics",
                    headers={
                        "Authorization": "Bearer wrong-token",
                    },
                )
                assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_401_missing_token(self, test_db):
        """Verify auth rejection when no token is provided."""
        with patch.object(config, "API_SECRET_KEY", "real-secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/topics")
                assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_health_no_auth_required(self, test_db):
        """Health check should work even with auth enabled."""
        with patch.object(config, "API_SECRET_KEY", "real-secret"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/health")
                assert resp.status_code == 200
