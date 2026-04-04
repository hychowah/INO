"""Tests for db.get_due_forecast and db.get_forecast_bucket_concepts."""

import pytest
from datetime import datetime, timedelta

import db


# ============================================================================
# Helpers
# ============================================================================

def _add_concept(title: str, mastery: float = 50.0, days_until_due: int | None = None):
    """Add a concept and optionally set mastery and next_review_at."""
    cid = db.add_concept(title)
    conn = db._conn()
    updates = {"mastery_level": mastery}
    if days_until_due is not None:
        due_date = (datetime.now() + timedelta(days=days_until_due)).strftime("%Y-%m-%d")
        updates["next_review_at"] = due_date
    else:
        # Clear the default next_review_at so it doesn't pollute bucket 0
        updates["next_review_at"] = None
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn.execute(f"UPDATE concepts SET {set_clause} WHERE id = ?", (*updates.values(), cid))
    conn.commit()
    conn.close()
    return cid


# ============================================================================
# get_due_forecast — basic structure
# ============================================================================

class TestGetDueForecastStructure:
    def test_returns_correct_keys(self, test_db):
        result = db.get_due_forecast("weeks")
        assert set(result.keys()) == {"range_type", "overdue_count", "buckets"}

    def test_range_type_echoed(self, test_db):
        for rt in ("days", "weeks", "months"):
            res = db.get_due_forecast(rt)
            assert res["range_type"] == rt

    def test_seven_buckets_returned(self, test_db):
        for rt in ("days", "weeks", "months"):
            res = db.get_due_forecast(rt)
            assert len(res["buckets"]) == 7, f"{rt} should have 7 buckets"

    def test_bucket_keys_zero_to_six(self, test_db):
        res = db.get_due_forecast("days")
        keys = [b["bucket_key"] for b in res["buckets"]]
        assert keys == ["0", "1", "2", "3", "4", "5", "6"]

    def test_bucket_has_required_fields(self, test_db):
        res = db.get_due_forecast("weeks")
        for b in res["buckets"]:
            assert "label" in b
            assert "bucket_key" in b
            assert "count" in b
            assert "avg_mastery" in b

    def test_invalid_range_type_raises(self, test_db):
        with pytest.raises(ValueError, match="Invalid range_type"):
            db.get_due_forecast("decades")


# ============================================================================
# get_due_forecast — empty DB
# ============================================================================

class TestGetDueForecastEmptyDB:
    def test_empty_db_all_zeros(self, test_db):
        res = db.get_due_forecast("weeks")
        assert res["overdue_count"] == 0
        for b in res["buckets"]:
            assert b["count"] == 0

    def test_empty_db_days(self, test_db):
        res = db.get_due_forecast("days")
        assert res["overdue_count"] == 0
        assert all(b["count"] == 0 for b in res["buckets"])

    def test_empty_db_months(self, test_db):
        res = db.get_due_forecast("months")
        assert res["overdue_count"] == 0
        assert all(b["count"] == 0 for b in res["buckets"])


# ============================================================================
# get_due_forecast — Overdue bucket is distinct
# ============================================================================

class TestGetDueForecastOverdue:
    def test_overdue_concept_counted_in_overdue(self, test_db):
        """A concept past due must appear in overdue_count, not in rolling buckets."""
        _add_concept("Past Due", days_until_due=-1)
        res = db.get_due_forecast("days")
        assert res["overdue_count"] == 1
        # Must NOT appear in bucket 0 (today)
        assert res["buckets"][0]["count"] == 0

    def test_multiple_overdue_counted(self, test_db):
        _add_concept("A", days_until_due=-1)
        _add_concept("B", days_until_due=-10)
        _add_concept("C", days_until_due=-30)
        res = db.get_due_forecast("weeks")
        assert res["overdue_count"] == 3

    def test_overdue_not_in_weeks_buckets(self, test_db):
        _add_concept("Old", days_until_due=-5)
        res = db.get_due_forecast("weeks")
        total_bucket = sum(b["count"] for b in res["buckets"])
        # The overdue concept must not pollute any rolling bucket
        assert total_bucket == 0


# ============================================================================
# get_due_forecast — rolling window placement
# ============================================================================

class TestGetDueForecastWindows:
    def test_today_concept_in_bucket_0_days(self, test_db):
        _add_concept("Today", days_until_due=0)
        res = db.get_due_forecast("days")
        assert res["buckets"][0]["count"] == 1

    def test_tomorrow_concept_in_bucket_1_days(self, test_db):
        _add_concept("Tomorrow", days_until_due=1)
        res = db.get_due_forecast("days")
        assert res["buckets"][0]["count"] == 0
        assert res["buckets"][1]["count"] == 1

    def test_week_1_in_bucket_0_weeks(self, test_db):
        """Day 3 is within the first 7-day window (bucket 0 for weeks)."""
        _add_concept("Soon", days_until_due=3)
        res = db.get_due_forecast("weeks")
        assert res["buckets"][0]["count"] == 1

    def test_day_7_in_bucket_1_weeks(self, test_db):
        """Day 7 starts bucket 1 for weeks (7-day windows)."""
        _add_concept("NextWeek", days_until_due=7)
        res = db.get_due_forecast("weeks")
        assert res["buckets"][0]["count"] == 0
        assert res["buckets"][1]["count"] == 1

    def test_no_review_at_excluded(self, test_db):
        """Concepts with no next_review_at must be excluded from all counts."""
        _add_concept("No Due Date", mastery=50.0)  # days_until_due=None → NULL
        res = db.get_due_forecast("days")
        assert res["overdue_count"] == 0
        assert all(b["count"] == 0 for b in res["buckets"])


# ============================================================================
# get_due_forecast — avg_mastery
# ============================================================================

class TestGetDueForecastAvgMastery:
    def test_avg_mastery_computed(self, test_db):
        _add_concept("A", mastery=20.0, days_until_due=0)
        _add_concept("B", mastery=60.0, days_until_due=0)  # avg = 40.0
        res = db.get_due_forecast("days")
        b0 = res["buckets"][0]
        assert b0["count"] == 2
        assert b0["avg_mastery"] == pytest.approx(40.0, abs=0.2)

    def test_empty_bucket_zero_avg(self, test_db):
        res = db.get_due_forecast("days")
        for b in res["buckets"]:
            assert b["avg_mastery"] == 0.0


# ============================================================================
# get_forecast_bucket_concepts
# ============================================================================

class TestGetForecastBucketConcepts:
    def test_overdue_bucket(self, test_db):
        cid = _add_concept("Past", mastery=30.0, days_until_due=-3)
        concepts = db.get_forecast_bucket_concepts("days", "overdue")
        assert len(concepts) == 1
        assert concepts[0]["id"] == cid
        assert concepts[0]["title"] == "Past"

    def test_today_bucket(self, test_db):
        cid = _add_concept("Today", mastery=55.0, days_until_due=0)
        concepts = db.get_forecast_bucket_concepts("days", "0")
        assert any(c["id"] == cid for c in concepts)

    def test_sorted_mastery_asc(self, test_db):
        """Concepts returned sorted by mastery_level ASC (worst first)."""
        _add_concept("High", mastery=80.0, days_until_due=0)
        _add_concept("Low",  mastery=10.0, days_until_due=0)
        concepts = db.get_forecast_bucket_concepts("days", "0")
        masteries = [c["mastery_level"] for c in concepts]
        assert masteries == sorted(masteries)

    def test_invalid_bucket_key_returns_empty(self, test_db):
        """A non-integer bucket_key (other than 'overdue') returns empty list."""
        result = db.get_forecast_bucket_concepts("days", "notanumber")
        assert result == []

    def test_invalid_range_type_raises(self, test_db):
        with pytest.raises(ValueError):
            db.get_forecast_bucket_concepts("decades", "0")

    def test_empty_db_returns_empty(self, test_db):
        for rt in ("days", "weeks", "months"):
            assert db.get_forecast_bucket_concepts(rt, "0") == []
            assert db.get_forecast_bucket_concepts(rt, "overdue") == []

    def test_concepts_have_expected_fields(self, test_db):
        _add_concept("Test", mastery=50.0, days_until_due=0)
        concepts = db.get_forecast_bucket_concepts("days", "0")
        assert len(concepts) == 1
        c = concepts[0]
        assert "id" in c
        assert "title" in c
        assert "mastery_level" in c
        assert "next_review_at" in c
