"""Tests for topic-parent heuristics in services.tools."""

import db


class TestResolveTopicIdsAutoParent:
    """When _resolve_topic_ids auto-creates a topic from topic_titles,
    it should use semantic search to find and set parent topics."""

    def test_auto_parents_when_similar_topic_exists(self, test_db, monkeypatch):
        """If 'Python' exists and we create 'Python AST' via topic_titles,
        it should be auto-parented under Python."""
        from services import tools

        parent_id = db.add_topic(title="Python", description="Python language")

        def fake_search(query, limit=10, score_threshold=0.3):
            if "Python" in query:
                return [{"id": parent_id, "title": "Python", "score": 0.72}]
            return []

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Python AST"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]
        assert new_id in topic_ids

        parents = db.get_topic_parents(new_id)
        assert len(parents) == 1
        assert parents[0]["id"] == parent_id

    def test_no_auto_parent_when_no_similar(self, test_db, monkeypatch):
        """If no similar topic exists, the new topic should be a root."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return []

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Quantum Physics"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]
        assert new_id in topic_ids
        parents = db.get_topic_parents(new_id)
        assert len(parents) == 0

    def test_no_crash_when_vector_store_unavailable(self, test_db, monkeypatch):
        """If semantic search raises, auto-creation should still succeed."""
        from services import tools

        def raise_search(query, limit=10, score_threshold=0.3):
            raise RuntimeError("Qdrant not available")

        monkeypatch.setattr(db, "search_similar_topics", raise_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["New Topic"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]
        assert new_id in topic_ids
        topic = db.get_topic(new_id)
        assert topic is not None

    def test_skips_exact_title_match(self, test_db, monkeypatch):
        """Semantic search returning the same title should not be used as parent."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 99, "title": "Python AST", "score": 0.95}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Python AST"],
            }
        )

        assert len(created) == 1
        new_id = created[0][0]
        assert new_id in topic_ids
        parents = db.get_topic_parents(new_id)
        assert len(parents) == 0

    def test_reuses_existing_topic_by_title(self, test_db):
        """If topic_titles matches an existing topic title, reuse it without creation."""
        from services import tools

        existing_id = db.add_topic(title="Statistics")

        topic_ids, created = tools._resolve_topic_ids(
            {
                "topic_titles": ["Statistics"],
            }
        )

        assert existing_id in topic_ids
        assert len(created) == 0


class TestFindCandidateParents:
    """Tests for _find_candidate_parents heuristic logic."""

    def test_high_similarity_shorter_title_accepted(self, test_db, monkeypatch):
        """High-similarity shorter titles are accepted as parents."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 42, "title": "Machine Learning", "score": 0.70}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Deep Learning Optimization")
        assert 42 in result

    def test_high_similarity_longer_title_rejected(self, test_db, monkeypatch):
        """High-similarity longer titles are rejected as parents."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 99, "title": "Python AST Visitor Pattern", "score": 0.80}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Python AST")
        assert result == []

    def test_substring_match_accepted_regardless_of_length(self, test_db, monkeypatch):
        """Substring matches are accepted even below the high-similarity threshold."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 10, "title": "Python", "score": 0.55}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Python AST")
        assert 10 in result

    def test_low_similarity_rejected(self, test_db, monkeypatch):
        """Low-similarity non-substring candidates are rejected."""
        from services import tools

        def fake_search(query, limit=10, score_threshold=0.3):
            return [{"id": 50, "title": "JavaScript", "score": 0.52}]

        monkeypatch.setattr(db, "search_similar_topics", fake_search)

        result = tools._find_candidate_parents("Python AST")
        assert result == []
