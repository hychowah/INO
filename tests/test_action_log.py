"""Tests for db.action_log and the tools.py logging hook."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import db
from db import action_log
from db import core as db_core

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Redirect all DB operations to a temp directory so tests don't touch real data."""
    test_db = tmp_path / "knowledge.db"
    monkeypatch.setattr(db_core, "KNOWLEDGE_DB", test_db)
    monkeypatch.setattr(db_core, "CHAT_DB", tmp_path / "chat_history.db")
    monkeypatch.setattr(db_core, "DATA_DIR", tmp_path)
    db.init_databases()
    yield


# ============================================================================
# log_action
# ============================================================================


class TestLogAction:
    def test_basic_insert(self):
        entry_id = action_log.log_action(
            action="add_concept",
            params={"title": "Test Concept", "topic_ids": [1]},
            result_type="success",
            result="Created concept #1",
            source="discord",
        )
        assert entry_id > 0

    def test_returns_incrementing_ids(self):
        id1 = action_log.log_action("add_topic", {"title": "T1"}, "success", "ok")
        id2 = action_log.log_action("add_topic", {"title": "T2"}, "success", "ok")
        assert id2 > id1

    def test_params_truncated(self):
        big_params = {"data": "x" * 3000}
        action_log.log_action("add_concept", big_params, "success", "ok")
        entries = action_log.get_action_log(limit=1)
        assert len(entries) == 1
        assert len(entries[0]["params"]) <= action_log._MAX_PARAMS_LEN

    def test_result_truncated(self):
        big_result = "y" * 1000
        action_log.log_action("add_concept", {}, "success", big_result)
        entries = action_log.get_action_log(limit=1)
        assert len(entries[0]["result"]) <= action_log._MAX_RESULT_LEN

    def test_none_params_stored_as_none(self):
        action_log.log_action("quiz", None, "success", "ok")
        entries = action_log.get_action_log(limit=1)
        assert entries[0]["params"] is None

    def test_string_params_stored(self):
        action_log.log_action("quiz", "raw string", "success", "ok")
        entries = action_log.get_action_log(limit=1)
        assert entries[0]["params"] == "raw string"


# ============================================================================
# get_action_log — filtering
# ============================================================================


class TestGetActionLog:
    def _populate(self):
        action_log.log_action("add_concept", {"title": "A"}, "success", "ok", source="discord")
        action_log.log_action(
            "assess", {"concept_id": 1, "quality": 4}, "success", "ok", source="scheduler"
        )
        action_log.log_action("add_topic", {"title": "B"}, "success", "ok", source="maintenance")
        action_log.log_action(
            "update_concept", {"concept_id": 2}, "error", "failed", source="discord"
        )

    def test_returns_all(self):
        self._populate()
        entries = action_log.get_action_log(limit=100)
        assert len(entries) == 4

    def test_ordered_desc(self):
        self._populate()
        entries = action_log.get_action_log(limit=100)
        # Most recent first — entries have same second, so order by rowid DESC
        ids = [e["id"] for e in entries]
        assert ids == sorted(ids, reverse=True)

    def test_filter_by_action(self):
        self._populate()
        entries = action_log.get_action_log(action_filter="add_concept")
        assert len(entries) == 1
        assert entries[0]["action"] == "add_concept"

    def test_filter_by_source(self):
        self._populate()
        entries = action_log.get_action_log(source_filter="scheduler")
        assert len(entries) == 1
        assert entries[0]["source"] == "scheduler"

    def test_filter_by_search(self):
        self._populate()
        entries = action_log.get_action_log(search="quality")
        assert len(entries) == 1  # only the assess entry has "quality" in params

    def test_filter_by_since(self):
        self._populate()
        # All entries are from right now, so "since 1 hour ago" should return all
        entries = action_log.get_action_log(since=datetime.now() - timedelta(hours=1))
        assert len(entries) == 4
        # "since tomorrow" should return none
        entries = action_log.get_action_log(since=datetime.now() + timedelta(days=1))
        assert len(entries) == 0

    def test_pagination(self):
        self._populate()
        page1 = action_log.get_action_log(limit=2, offset=0)
        page2 = action_log.get_action_log(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        # No overlap
        ids1 = {e["id"] for e in page1}
        ids2 = {e["id"] for e in page2}
        assert ids1.isdisjoint(ids2)

    def test_combined_filters(self):
        self._populate()
        entries = action_log.get_action_log(action_filter="add_concept", source_filter="discord")
        assert len(entries) == 1


# ============================================================================
# get_action_log_count
# ============================================================================


class TestGetActionLogCount:
    def test_total(self):
        action_log.log_action("add_concept", {}, "success", "ok")
        action_log.log_action("assess", {}, "success", "ok")
        assert action_log.get_action_log_count() == 2

    def test_filtered(self):
        action_log.log_action("add_concept", {}, "success", "ok", source="discord")
        action_log.log_action("assess", {}, "success", "ok", source="scheduler")
        assert action_log.get_action_log_count(source_filter="discord") == 1


# ============================================================================
# get_action_summary
# ============================================================================


class TestGetActionSummary:
    def test_basic_summary(self):
        action_log.log_action("add_concept", {}, "success", "ok")
        action_log.log_action("add_concept", {}, "success", "ok")
        action_log.log_action("assess", {}, "success", "ok")
        summary = action_log.get_action_summary(days=7)
        assert summary["total"] == 3
        assert summary["today_total"] == 3
        assert summary["by_action"]["add_concept"] == 2
        assert summary["by_action"]["assess"] == 1
        assert summary["today_by_action"]["add_concept"] == 2

    def test_empty_summary(self):
        summary = action_log.get_action_summary(days=7)
        assert summary["total"] == 0
        assert summary["today_total"] == 0
        assert summary["by_action"] == {}


# ============================================================================
# get_distinct_actions / get_distinct_sources
# ============================================================================


class TestDistinctValues:
    def test_distinct_actions(self):
        action_log.log_action("add_concept", {}, "success", "ok")
        action_log.log_action("assess", {}, "success", "ok")
        action_log.log_action("add_concept", {}, "success", "ok")
        actions = action_log.get_distinct_actions()
        assert set(actions) == {"add_concept", "assess"}

    def test_distinct_sources(self):
        action_log.log_action("add_concept", {}, "success", "ok", source="discord")
        action_log.log_action("assess", {}, "success", "ok", source="scheduler")
        sources = action_log.get_distinct_sources()
        assert set(sources) == {"discord", "scheduler"}

    def test_empty(self):
        assert action_log.get_distinct_actions() == []
        assert action_log.get_distinct_sources() == []


# ============================================================================
# cleanup_old_actions
# ============================================================================


class TestCleanup:
    def test_deletes_old_entries(self):
        # Insert an entry, then manually age it
        action_log.log_action("add_concept", {}, "success", "ok")
        conn = db_core._conn()
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE action_log SET created_at = ?", (old_date,))
        conn.commit()
        conn.close()

        # Also add a fresh entry
        action_log.log_action("assess", {}, "success", "ok")

        deleted = action_log.cleanup_old_actions(days=90)
        assert deleted == 1
        remaining = action_log.get_action_log_count()
        assert remaining == 1

    def test_keeps_recent(self):
        action_log.log_action("add_concept", {}, "success", "ok")
        deleted = action_log.cleanup_old_actions(days=90)
        assert deleted == 0
        assert action_log.get_action_log_count() == 1


# ============================================================================
# tools.py skip set behavior
# ============================================================================


class TestToolsSkipSet:
    def test_skip_actions_not_logged(self):
        from services.tools import _SKIP_LOG_ACTIONS

        assert "fetch" in _SKIP_LOG_ACTIONS
        assert "list_topics" in _SKIP_LOG_ACTIONS
        assert "none" in _SKIP_LOG_ACTIONS
        assert "reply" in _SKIP_LOG_ACTIONS

    def test_mutation_actions_not_in_skip(self):
        from services.tools import _SKIP_LOG_ACTIONS

        assert "add_concept" not in _SKIP_LOG_ACTIONS
        assert "assess" not in _SKIP_LOG_ACTIONS
        assert "quiz" not in _SKIP_LOG_ACTIONS
        assert "suggest_topic" not in _SKIP_LOG_ACTIONS


# ============================================================================
# webui._relative_time
# ============================================================================


class TestRelativeTime:
    def test_just_now(self):
        from webui.server import _relative_time

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        assert _relative_time(now) == "just now"

    def test_minutes(self):
        from webui.server import _relative_time

        t = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        assert "5 min ago" == _relative_time(t)

    def test_hours(self):
        from webui.server import _relative_time

        t = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        assert "3 hrs ago" == _relative_time(t)

    def test_yesterday(self):
        from webui.server import _relative_time

        t = (datetime.now() - timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        assert _relative_time(t) == "yesterday"

    def test_days(self):
        from webui.server import _relative_time

        t = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        assert "10 days ago" == _relative_time(t)

    def test_old_date(self):
        from webui.server import _relative_time

        assert _relative_time("2020-01-15 10:30:00").startswith("2020")

    def test_invalid(self):
        from webui.server import _relative_time

        assert _relative_time(None) == "—"
        assert _relative_time("not a date") == "not a date"


# ============================================================================
# webui._esc
# ============================================================================


class TestEsc:
    def test_escapes_html(self):
        from webui.server import _esc

        assert _esc('<script>"hello"&') == "&lt;script&gt;&quot;hello&quot;&amp;"

    def test_empty(self):
        from webui.server import _esc

        assert _esc("") == ""
