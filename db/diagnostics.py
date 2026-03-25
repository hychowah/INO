"""
Maintenance diagnostics and duplicate detection.
"""

import re
import sqlite3
from typing import List, Dict, Any

from db.core import _conn, _now_iso
from datetime import datetime, timedelta

DIAG_LIMIT = 20

# Stop words excluded from title similarity comparison
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'in', 'of', 'for', 'and', 'or', 'vs', 'to', 'on',
    'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
})


def _stem(word: str) -> str:
    """Minimal suffix stripping for title comparison."""
    if len(word) <= 3:
        return word
    for suffix in ('ings', 'ing', 'tion', 'sion', 'ers', 'er', 'eds', 'ed', 'ies', 'es', 's'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def _title_similarity(a: str, b: str) -> float:
    """Word-overlap similarity between two concept titles.
    Returns 0.0–1.0. Ignores stop words, case, punctuation, and common suffixes.
    Uses max(Jaccard, containment) so "Bootloader" matches "Bootloader in
    Embedded Systems" even though Jaccard alone would be low."""
    words_a = {_stem(w) for w in re.findall(r'[a-z0-9]+', a.lower())} - _STOP_WORDS
    words_b = {_stem(w) for w in re.findall(r'[a-z0-9]+', b.lower())} - _STOP_WORDS
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union)
    containment = len(intersection) / min(len(words_a), len(words_b))
    return max(jaccard, containment)


def _get_relationship_candidates(conn, limit: int = 20) -> List[Dict]:
    """Find semantically related concept pairs that don't have a relation yet.

    Uses vector store nearest-neighbor search when available (semantic matching).
    Falls back to FTS5-based keyword matching + title similarity.
    Returns up to `limit` candidate pairs.
    """
    # Try vector-based discovery first
    try:
        from db.vectors import find_nearest_concepts
        from config import SIMILARITY_THRESHOLD_RELATION

        all_concepts = conn.execute(
            "SELECT id, title FROM concepts ORDER BY id"
        ).fetchall()
        if len(all_concepts) < 2:
            return []

        # Get existing relations to exclude
        try:
            existing = conn.execute(
                "SELECT concept_id_low, concept_id_high FROM concept_relations"
            ).fetchall()
            existing_pairs = {(r['concept_id_low'], r['concept_id_high']) for r in existing}
        except sqlite3.OperationalError:
            existing_pairs = set()

        candidates = []
        seen_pairs = set()

        for concept in all_concepts:
            neighbors = find_nearest_concepts(
                concept['id'], limit=5,
                score_threshold=SIMILARITY_THRESHOLD_RELATION,
            )
            for neighbor in neighbors:
                low = min(concept['id'], neighbor['id'])
                high = max(concept['id'], neighbor['id'])
                if (low, high) in existing_pairs or (low, high) in seen_pairs:
                    continue
                candidates.append({
                    'concept_a': {'id': concept['id'], 'title': concept['title']},
                    'concept_b': {'id': neighbor['id'], 'title': neighbor['title']},
                    'similarity': neighbor['score'],
                })
                seen_pairs.add((low, high))
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break

        return candidates
    except Exception:
        pass  # Fall through to FTS5-based approach

    # FTS5 fallback (original implementation)
    all_concepts = conn.execute(
        "SELECT id, title FROM concepts ORDER BY id"
    ).fetchall()

    if len(all_concepts) < 2:
        return []

    candidates = []
    seen_pairs = set()

    try:
        existing = conn.execute(
            "SELECT concept_id_low, concept_id_high FROM concept_relations"
        ).fetchall()
        existing_pairs = {(r['concept_id_low'], r['concept_id_high']) for r in existing}
    except sqlite3.OperationalError:
        existing_pairs = set()

    for concept in all_concepts:
        words = {_stem(w) for w in re.findall(r'[a-z0-9]+', concept['title'].lower())} - _STOP_WORDS
        keywords = [w for w in words if len(w) >= 3]
        if not keywords:
            continue

        fts_query = ' OR '.join(f'"{kw}"' for kw in keywords[:5])
        try:
            matches = conn.execute("""
                SELECT c.id, c.title
                FROM concepts c
                JOIN concepts_fts fts ON c.id = fts.rowid
                WHERE concepts_fts MATCH ? AND c.id != ?
                ORDER BY rank
                LIMIT 5
            """, (fts_query, concept['id'])).fetchall()
        except sqlite3.OperationalError:
            continue

        for match in matches:
            low, high = min(concept['id'], match['id']), max(concept['id'], match['id'])
            if (low, high) in existing_pairs or (low, high) in seen_pairs:
                continue

            sim = _title_similarity(concept['title'], match['title'])
            if sim >= 0.3:
                candidates.append({
                    'concept_a': {'id': concept['id'], 'title': concept['title']},
                    'concept_b': {'id': match['id'], 'title': match['title']},
                    'similarity': round(sim, 2),
                })
                seen_pairs.add((low, high))

            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    return candidates


def get_maintenance_diagnostics() -> Dict[str, Any]:
    """Run diagnostic queries for the maintenance agent. Surfaces issues like
    untagged concepts, empty topics, oversized topics, stale concepts, etc."""
    conn = _conn()
    now = _now_iso()

    # 1. Untagged concepts (no topic link)
    untagged = conn.execute("""
        SELECT c.id, c.title, c.mastery_level, c.review_count, c.created_at
        FROM concepts c
        LEFT JOIN concept_topics ct ON c.id = ct.concept_id
        WHERE ct.topic_id IS NULL
        ORDER BY c.created_at DESC
        LIMIT 20
    """).fetchall()

    # 2. Empty topics (no concepts linked AND no child topics)
    empty_topics = conn.execute("""
        SELECT t.id, t.title, t.created_at
        FROM topics t
        LEFT JOIN concept_topics ct ON t.id = ct.topic_id
        LEFT JOIN topic_relations tr ON t.id = tr.parent_id
        WHERE ct.concept_id IS NULL AND tr.child_id IS NULL
        ORDER BY t.created_at DESC
        LIMIT 20
    """).fetchall()

    # 3. Oversized topics (>15 concepts)
    oversized = conn.execute("""
        SELECT t.id, t.title, COUNT(ct.concept_id) as concept_count
        FROM topics t
        JOIN concept_topics ct ON t.id = ct.topic_id
        GROUP BY t.id
        HAVING concept_count > 15
        ORDER BY concept_count DESC
        LIMIT 20
    """).fetchall()

    # 4. Stale concepts (created >14 days ago, never reviewed)
    fourteen_days_ago = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
    stale = conn.execute("""
        SELECT c.id, c.title, c.created_at, c.review_count
        FROM concepts c
        WHERE c.review_count = 0 AND c.created_at <= ?
        ORDER BY c.created_at ASC
        LIMIT 20
    """, (fourteen_days_ago,)).fetchall()

    # 5. Low score concepts with many reviews (struggling)
    struggling = conn.execute("""
        SELECT c.id, c.title, c.mastery_level, c.ease_factor, c.review_count
        FROM concepts c
        WHERE c.review_count >= 5 AND c.mastery_level <= 25
        ORDER BY c.review_count DESC
        LIMIT 20
    """).fetchall()

    # 6. Concepts in many topics (>3 — potential over-tagging)
    over_tagged = conn.execute("""
        SELECT c.id, c.title, COUNT(ct.topic_id) as topic_count
        FROM concepts c
        JOIN concept_topics ct ON c.id = ct.concept_id
        GROUP BY c.id
        HAVING topic_count > 3
        ORDER BY topic_count DESC
        LIMIT 20
    """).fetchall()

    # 7. Potential duplicate concepts (word-overlap similarity)
    all_concepts = conn.execute(
        "SELECT id, title FROM concepts ORDER BY id"
    ).fetchall()
    potential_dupes = []
    concept_list = [dict(c) for c in all_concepts]
    for i, a in enumerate(concept_list):
        for b in concept_list[i + 1:]:
            if _title_similarity(a['title'], b['title']) >= 0.5:
                potential_dupes.append({
                    'concept_a': {'id': a['id'], 'title': a['title']},
                    'concept_b': {'id': b['id'], 'title': b['title']},
                })
                if len(potential_dupes) >= DIAG_LIMIT:
                    break
        if len(potential_dupes) >= DIAG_LIMIT:
            break

    # 8. Relationship candidates — FTS5-based concept pairs that share keywords
    #    but don't yet have a relation.
    relationship_candidates = _get_relationship_candidates(conn, limit=DIAG_LIMIT)

    # 9. Cluttered root topics — roots with >10 direct concepts and no subtopics
    cluttered_roots = conn.execute("""
        SELECT t.id, t.title, COUNT(ct.concept_id) as concept_count
        FROM topics t
        JOIN concept_topics ct ON t.id = ct.topic_id
        WHERE t.id NOT IN (SELECT child_id FROM topic_relations)
          AND t.id NOT IN (SELECT parent_id FROM topic_relations)
        GROUP BY t.id
        HAVING concept_count > 10
        ORDER BY concept_count DESC
        LIMIT ?
    """, (DIAG_LIMIT,)).fetchall()

    conn.close()

    return {
        'untagged_concepts': [dict(r) for r in untagged],
        'empty_topics': [dict(r) for r in empty_topics],
        'oversized_topics': [dict(r) for r in oversized],
        'stale_concepts': [dict(r) for r in stale],
        'struggling_concepts': [dict(r) for r in struggling],
        'over_tagged_concepts': [dict(r) for r in over_tagged],
        'potential_duplicates': potential_dupes,
        'relationship_candidates': relationship_candidates,
        'cluttered_root_topics': [dict(r) for r in cluttered_roots],
    }
