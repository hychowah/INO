"""Direct tests for services.dedup."""

import asyncio

import db
from services import dedup


class TestParseDedupResponse:
    def test_parses_fenced_json_groups(self):
        raw = """```json
        [
          {"keep": "10", "merge": [11, "12"], "reason": "same concept"}
        ]
        ```"""

        groups = dedup._parse_dedup_response(raw)

        assert groups == [{"keep": 10, "merge": [11, 12], "reason": "same concept"}]

    def test_ignores_invalid_entries_and_returns_valid_ones(self):
        raw = """[
        {"keep": 5, "merge": [6]},
        {"keep": 9},
        "bad"
        ]"""

        groups = dedup._parse_dedup_response(raw)

        assert groups == [{"keep": 5, "merge": [6], "reason": ""}]

    def test_returns_none_for_malformed_json(self):
        assert dedup._parse_dedup_response("not json at all") is None
        assert dedup._parse_dedup_response("[{bad}") is None


class TestFormatDedupSuggestions:
    def test_formats_keep_and_delete_entries(self, test_db):
        keep_id = db.add_concept("Embedding Models", "Dense vector topic")
        merge_id = db.add_concept("Text Embeddings", "Same idea, different title")
        db.update_concept(keep_id, mastery_level=80, review_count=5)
        db.update_concept(merge_id, mastery_level=30, review_count=1)

        message = dedup.format_dedup_suggestions(
            [{"keep": keep_id, "merge": [merge_id], "reason": "same learning target"}]
        )

        assert "Potential Duplicate Concepts" in message
        assert "Embedding Models" in message
        assert "Text Embeddings" in message
        assert "same learning target" in message


class TestExecuteDedupMerges:
    def test_execute_dedup_merges_moves_remarks_and_deletes_duplicates(self, test_db):
        keep_id = db.add_concept("Embedding Models", "Dense vector topic")
        merge_id = db.add_concept("Text Embeddings", "Same idea, different title")

        db.add_remark(merge_id, "Useful mental model")
        db.add_remark(merge_id, "Compare cosine vs dot product")

        summaries = asyncio.run(
            dedup.execute_dedup_merges(
                [{"keep": keep_id, "merge": [merge_id], "reason": "same concept"}]
            )
        )

        keep_detail = db.get_concept_detail(keep_id)

        assert len(summaries) == 1
        assert f'#{merge_id} "Text Embeddings"' in summaries[0]
        assert db.get_concept(merge_id) is None
        assert keep_detail is not None
        assert len(keep_detail["remarks"]) == 2
        assert all("[merged from #" in remark["content"] for remark in keep_detail["remarks"])
        assert "[merged from #" in keep_detail["remark_summary"]

    def test_execute_dedup_merges_skips_missing_keep_target(self, test_db):
        merge_id = db.add_concept("Duplicate", "desc")

        summaries = asyncio.run(
            dedup.execute_dedup_merges(
                [{"keep": 99999, "merge": [merge_id], "reason": "missing keep"}]
            )
        )

        assert summaries == []
        assert db.get_concept(merge_id) is not None
