"""
Shared test fixtures for the learning agent test suite.

Provides an isolated temporary database so tests don't touch the real DB.
Vector store init is skipped by default to avoid requiring the embedding
model in normal tests.
"""

import pytest
from unittest.mock import patch
from pathlib import Path

import db
from db import core


@pytest.fixture
def test_db(tmp_path):
    """Provide isolated temporary databases for tests.

    Patches KNOWLEDGE_DB and CHAT_DB to point to files in tmp_path,
    then initializes schemas + migrations. Yields the tmp_path.
    Vector store init is skipped (no embedding model needed).
    """
    knowledge = tmp_path / "knowledge.db"
    chat = tmp_path / "chat_history.db"

    with patch.object(core, 'KNOWLEDGE_DB', knowledge), \
         patch.object(core, 'CHAT_DB', chat), \
         patch('db.core.KNOWLEDGE_DB', knowledge), \
         patch('db.core.CHAT_DB', chat), \
         patch('db.core._init_vector_store'):
        # Also patch the module-level reference that _conn() uses
        import db.topics
        import db.concepts
        import db.relations
        import db.reviews
        import db.chat
        import db.diagnostics
        import db.proposals
        import db.action_log

        original_knowledge = {}
        modules_to_patch = [
            db.topics, db.concepts, db.relations, db.reviews,
            db.chat, db.diagnostics, db.proposals, db.action_log,
        ]

        # Store originals and patch
        for mod in modules_to_patch:
            if hasattr(mod, 'KNOWLEDGE_DB'):
                original_knowledge[mod] = mod.KNOWLEDGE_DB

        for mod in modules_to_patch:
            if hasattr(mod, 'KNOWLEDGE_DB'):
                mod.KNOWLEDGE_DB = knowledge

        # Init
        core.DATA_DIR.mkdir(parents=True, exist_ok=True)
        db.init_databases()

        yield tmp_path

        # Restore
        for mod, orig in original_knowledge.items():
            mod.KNOWLEDGE_DB = orig
