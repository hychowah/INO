"""
Shared test fixtures for the learning agent test suite.

Provides an isolated temporary database so tests don't touch the real DB.
Vector store init is skipped by default to avoid requiring the embedding
model in normal tests.
"""

import os
import shutil
from unittest.mock import patch

import pytest

from db import core

_UNIT_TEST_MODULES = {
    "test_formatting.py",
    "test_forecast.py",
    "test_llm.py",
    "test_llm_errors.py",
    "test_parser_json.py",
    "test_persona.py",
    "test_quiz_generator_script.py",
    "test_skill_loading.py",
    "test_state_lock.py",
}


def pytest_collection_modifyitems(config, items):
    """Require every collected test to carry either the unit or integration marker.

    Pure logic modules stay on the unit lane; everything else defaults to
    integration unless a test already opted into one of the suite markers.
    """
    del config

    for item in items:
        if item.get_closest_marker("unit") or item.get_closest_marker("integration"):
            continue

        if item.path.name in _UNIT_TEST_MODULES:
            item.add_marker(pytest.mark.unit)
            continue

        item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session", autouse=True)
def _disable_vector_sync_for_tests():
    """Keep ordinary tests from loading the embedding model via add/update helpers."""
    original = os.environ.get("LEARN_DISABLE_VECTOR_SYNC")
    os.environ["LEARN_DISABLE_VECTOR_SYNC"] = "1"
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("LEARN_DISABLE_VECTOR_SYNC", None)
        else:
            os.environ["LEARN_DISABLE_VECTOR_SYNC"] = original


@pytest.fixture
def anyio_backend():
    """Restrict anyio tests to asyncio only (avoids running each test twice on asyncio+trio)."""
    return "asyncio"


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    """Create a fully-initialised SQLite DB pair once per worker session.

    Returns (knowledge_path, chat_path). test_db copies these instead of
    re-running init_databases() for every test, cutting ~300 migration runs
    down to 1 per worker.
    """
    base = tmp_path_factory.mktemp("db_template")
    knowledge = base / "knowledge.db"
    chat = base / "chat_history.db"

    with (
        patch.object(core, "KNOWLEDGE_DB", knowledge),
        patch.object(core, "CHAT_DB", chat),
        patch("db.core.KNOWLEDGE_DB", knowledge),
        patch("db.core.CHAT_DB", chat),
        patch("db.core._init_vector_store"),
    ):
        import db.action_log
        import db.chat
        import db.concepts
        import db.diagnostics
        import db.proposals
        import db.relations
        import db.reviews
        import db.topics

        modules_to_patch = [
            db.topics,
            db.concepts,
            db.relations,
            db.reviews,
            db.chat,
            db.diagnostics,
            db.proposals,
            db.action_log,
        ]

        # Temporarily redirect all modules to the template paths
        original_knowledge = {
            mod: mod.KNOWLEDGE_DB for mod in modules_to_patch if hasattr(mod, "KNOWLEDGE_DB")
        }
        original_chat_db = db.chat.CHAT_DB

        for mod in modules_to_patch:
            if hasattr(mod, "KNOWLEDGE_DB"):
                mod.KNOWLEDGE_DB = knowledge
        db.chat.CHAT_DB = chat

        core.DATA_DIR.mkdir(parents=True, exist_ok=True)
        import db as _db

        _db.init_databases()

        # Restore originals before leaving the patch context
        for mod, orig in original_knowledge.items():
            mod.KNOWLEDGE_DB = orig
        db.chat.CHAT_DB = original_chat_db

    return knowledge, chat


@pytest.fixture
def test_db(tmp_path, _db_template):
    """Provide isolated temporary databases for tests.

    Copies the session-scoped template DB (already fully initialised) into
    tmp_path instead of re-running init_databases() on every test. This
    eliminates per-test migration overhead while preserving full isolation.
    """
    template_knowledge, template_chat = _db_template
    knowledge = tmp_path / "knowledge.db"
    chat = tmp_path / "chat_history.db"

    shutil.copy2(template_knowledge, knowledge)
    shutil.copy2(template_chat, chat)

    with (
        patch.object(core, "KNOWLEDGE_DB", knowledge),
        patch.object(core, "CHAT_DB", chat),
        patch("db.core.KNOWLEDGE_DB", knowledge),
        patch("db.core.CHAT_DB", chat),
        patch("db.core._init_vector_store"),
    ):
        import db.action_log
        import db.chat
        import db.concepts
        import db.diagnostics
        import db.proposals
        import db.relations
        import db.reviews
        import db.topics

        original_knowledge = {}
        original_chat = {}
        modules_to_patch = [
            db.topics,
            db.concepts,
            db.relations,
            db.reviews,
            db.chat,
            db.diagnostics,
            db.proposals,
            db.action_log,
        ]

        for mod in modules_to_patch:
            if hasattr(mod, "KNOWLEDGE_DB"):
                original_knowledge[mod] = mod.KNOWLEDGE_DB

        for mod in modules_to_patch:
            if hasattr(mod, "KNOWLEDGE_DB"):
                mod.KNOWLEDGE_DB = knowledge

        original_chat[db.chat] = db.chat.CHAT_DB
        db.chat.CHAT_DB = chat

        yield tmp_path

        for mod, orig in original_knowledge.items():
            mod.KNOWLEDGE_DB = orig
        for mod, orig in original_chat.items():
            mod.CHAT_DB = orig
