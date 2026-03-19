"""Tests for the maintenance score-field guard in tools._handle_update_concept.

Verifies that mastery_level, ease_factor, interval_days, next_review_at,
last_reviewed_at, and review_count are stripped from update_concept when
the action source is 'maintenance', but allowed from other sources.

See DEVNOTES.md §7 for bug history.

Run:  pytest tests/test_score_guard.py -v
"""

import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from db import core as db_core
from services import tools


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory."""
    monkeypatch.setattr(db_core, "KNOWLEDGE_DB", tmp_path / "knowledge.db")
    monkeypatch.setattr(db_core, "CHAT_DB", tmp_path / "chat_history.db")
    monkeypatch.setattr(db_core, "DATA_DIR", tmp_path)
    db.init_databases()
    yield


@pytest.fixture
def concept_id():
    """Create a topic and concept, return the concept ID."""
    tid = db.add_topic("Test Topic", "A test topic")
    cid = db.add_concept("Test Concept", "A test concept", topic_ids=[tid])
    return cid


# ============================================================================
# Maintenance source — score fields BLOCKED
# ============================================================================

class TestMaintenanceBlocked:
    """Maintenance source must not be able to change score/scheduling fields."""

    SCORE_FIELDS = {
        'mastery_level': 80,
        'ease_factor': 3.0,
        'interval_days': 30,
        'next_review_at': '2026-06-01 00:00:00',
        'last_reviewed_at': '2026-03-16 00:00:00',
        'review_count': 10,
    }

    def test_mastery_level_blocked(self, concept_id):
        tools.set_action_source('maintenance')
        tools.execute_action('update_concept', {
            'concept_id': concept_id,
            'mastery_level': 80,
        })
        concept = db.get_concept(concept_id)
        assert concept['mastery_level'] == 0, \
            "Maintenance should not be able to change mastery_level"

    def test_all_score_fields_blocked(self, concept_id):
        tools.set_action_source('maintenance')
        params = {'concept_id': concept_id, **self.SCORE_FIELDS}
        tools.execute_action('update_concept', params)

        concept = db.get_concept(concept_id)
        assert concept['mastery_level'] == 0
        assert concept['interval_days'] == 1  # default
        assert concept['review_count'] == 0

    def test_title_description_still_allowed(self, concept_id):
        tools.set_action_source('maintenance')
        tools.execute_action('update_concept', {
            'concept_id': concept_id,
            'title': 'Renamed Concept',
            'description': 'Updated description',
        })
        concept = db.get_concept(concept_id)
        assert concept['title'] == 'Renamed Concept'
        assert concept['description'] == 'Updated description'

    def test_mixed_fields_only_safe_applied(self, concept_id):
        """Score fields stripped, non-score fields applied."""
        tools.set_action_source('maintenance')
        tools.execute_action('update_concept', {
            'concept_id': concept_id,
            'title': 'New Title',
            'mastery_level': 90,
            'interval_days': 60,
        })
        concept = db.get_concept(concept_id)
        assert concept['title'] == 'New Title'
        assert concept['mastery_level'] == 0
        assert concept['interval_days'] == 1

    def test_remark_still_allowed(self, concept_id):
        tools.set_action_source('maintenance')
        tools.execute_action('update_concept', {
            'concept_id': concept_id,
            'mastery_level': 50,
            'remark': 'User struggles with chemistry aspect',
        })
        concept = db.get_concept(concept_id)
        assert concept['mastery_level'] == 0  # blocked
        # Remark should still be added (both history and summary)
        detail = db.get_concept_detail(concept_id)
        remarks = detail.get('remarks', [])
        assert any('chemistry' in r['content'] for r in remarks)
        # Summary cache should also be populated
        assert detail.get('remark_summary') is not None
        assert 'chemistry' in detail['remark_summary']


# ============================================================================
# Non-maintenance sources — score fields ALLOWED
# ============================================================================

class TestNonMaintenanceAllowed:
    """Normal sources (discord, api, cli) should still update score fields."""

    @pytest.mark.parametrize("source", ["discord", "api", "cli", "scheduler"])
    def test_mastery_level_allowed(self, concept_id, source):
        tools.set_action_source(source)
        tools.execute_action('update_concept', {
            'concept_id': concept_id,
            'mastery_level': 75,
        })
        concept = db.get_concept(concept_id)
        assert concept['mastery_level'] == 75

    def test_all_score_fields_allowed_from_discord(self, concept_id):
        tools.set_action_source('discord')
        tools.execute_action('update_concept', {
            'concept_id': concept_id,
            'mastery_level': 60,
            'interval_days': 14,
            'review_count': 5,
        })
        concept = db.get_concept(concept_id)
        assert concept['mastery_level'] == 60
        assert concept['interval_days'] == 14
        assert concept['review_count'] == 5
