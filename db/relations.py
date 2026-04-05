"""
Concept-to-concept relationship CRUD and queries.

Relationships are undirected edges between concept pairs, stored with
the smaller concept ID as `concept_id_low` and the larger as `concept_id_high`.
Each pair can have at most one relationship. Each concept is capped at 5 total
relationships to encourage quality over quantity.

Relation types (controlled vocabulary):
    builds_on          — A is helpful context for understanding B
    contrasts_with     — A and B are alternatives or opposites
    commonly_confused  — users often mix these up
    applied_together   — A and B are used together in practice
    same_phenomenon    — different aspects of the same thing
"""

import sqlite3
from typing import Dict, List, Optional

from db.core import _conn, _now_iso

# Maximum number of relationships allowed per concept
MAX_RELATIONS_PER_CONCEPT = 5

VALID_RELATION_TYPES = frozenset(
    {
        "builds_on",
        "contrasts_with",
        "commonly_confused",
        "applied_together",
        "same_phenomenon",
    }
)


def _normalize_pair(a: int, b: int) -> tuple[int, int]:
    """Return (low, high) so that low < high. Raises ValueError if a == b."""
    if a == b:
        raise ValueError("Cannot create a self-referential relationship")
    return (min(a, b), max(a, b))


def add_relation(
    concept_id_a: int,
    concept_id_b: int,
    relation_type: str = "builds_on",
    note: Optional[str] = None,
) -> Optional[int]:
    """Create a relationship between two concepts.

    Normalizes the direction (smaller ID stored as low), validates the
    relation_type, and enforces the per-concept cap.

    Returns the new relation ID, or None if it was rejected (duplicate,
    cap exceeded, invalid type, or invalid concept IDs).
    """
    if relation_type not in VALID_RELATION_TYPES:
        return None
    try:
        low, high = _normalize_pair(concept_id_a, concept_id_b)
    except ValueError:
        return None

    conn = _conn()
    try:
        # Cap check: neither concept should already have MAX_RELATIONS_PER_CONCEPT
        count_low = conn.execute(
            "SELECT COUNT(*) FROM concept_relations "
            "WHERE concept_id_low = ? OR concept_id_high = ?",
            (low, low),
        ).fetchone()[0]
        if count_low >= MAX_RELATIONS_PER_CONCEPT:
            return None

        count_high = conn.execute(
            "SELECT COUNT(*) FROM concept_relations "
            "WHERE concept_id_low = ? OR concept_id_high = ?",
            (high, high),
        ).fetchone()[0]
        if count_high >= MAX_RELATIONS_PER_CONCEPT:
            return None

        cursor = conn.execute(
            "INSERT OR IGNORE INTO concept_relations "
            "(concept_id_low, concept_id_high, relation_type, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (low, high, relation_type, note, _now_iso()),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None  # duplicate — already exists
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_relations(concept_id: int) -> List[Dict]:
    """Get all relationships for a concept (both directions).

    Returns a list of dicts, each with:
        id, other_concept_id, other_title, other_mastery, relation_type, note
    """
    conn = _conn()
    rows = conn.execute(
        """
        SELECT cr.id, cr.relation_type, cr.note,
               CASE WHEN cr.concept_id_low = ? THEN cr.concept_id_high
                    ELSE cr.concept_id_low END AS other_id,
               c.title AS other_title,
               c.mastery_level AS other_mastery
        FROM concept_relations cr
        JOIN concepts c ON c.id = CASE WHEN cr.concept_id_low = ?
                                       THEN cr.concept_id_high
                                       ELSE cr.concept_id_low END
        WHERE cr.concept_id_low = ? OR cr.concept_id_high = ?
        ORDER BY cr.created_at DESC
    """,
        (concept_id, concept_id, concept_id, concept_id),
    ).fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "other_concept_id": r["other_id"],
            "other_title": r["other_title"],
            "other_mastery": r["other_mastery"],
            "relation_type": r["relation_type"],
            "note": r["note"],
        }
        for r in rows
    ]


def remove_relation(concept_id_a: int, concept_id_b: int) -> bool:
    """Remove the relationship between two concepts. Returns True if one existed."""
    try:
        low, high = _normalize_pair(concept_id_a, concept_id_b)
    except ValueError:
        return False

    conn = _conn()
    cursor = conn.execute(
        "DELETE FROM concept_relations WHERE concept_id_low = ? AND concept_id_high = ?",
        (low, high),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def add_relations_from_assess(
    concept_id: int, related_ids: List[int], relation_type: str = "builds_on"
) -> int:
    """Batch-add relationships from a quiz assessment.

    Silently skips: self-references, invalid IDs, concepts at cap, duplicates.
    Returns the number of relations actually created.
    """
    if not related_ids or relation_type not in VALID_RELATION_TYPES:
        return 0

    created = 0
    conn = _conn()
    try:
        for rid in related_ids:
            if not isinstance(rid, int) or rid == concept_id:
                continue

            # Verify the related concept exists
            exists = conn.execute("SELECT 1 FROM concepts WHERE id = ?", (rid,)).fetchone()
            if not exists:
                continue

            low, high = min(concept_id, rid), max(concept_id, rid)

            # Cap check for both concepts
            for cid in (low, high):
                count = conn.execute(
                    "SELECT COUNT(*) FROM concept_relations "
                    "WHERE concept_id_low = ? OR concept_id_high = ?",
                    (cid, cid),
                ).fetchone()[0]
                if count >= MAX_RELATIONS_PER_CONCEPT:
                    break
            else:
                # Both under cap — insert
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO concept_relations "
                        "(concept_id_low, concept_id_high, relation_type, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (low, high, relation_type, _now_iso()),
                    )
                    # Check if it was actually a new insert (not a duplicate)
                    if conn.total_changes:
                        created += 1
                except sqlite3.IntegrityError:
                    pass

        conn.commit()
    finally:
        conn.close()
    return created


def get_all_relations() -> List[Dict]:
    """Get all concept relationships. Used for graph visualization."""
    conn = _conn()
    rows = conn.execute("""
        SELECT cr.id, cr.concept_id_low, cr.concept_id_high,
               cr.relation_type, cr.note,
               c1.title AS low_title, c2.title AS high_title
        FROM concept_relations cr
        JOIN concepts c1 ON c1.id = cr.concept_id_low
        JOIN concepts c2 ON c2.id = cr.concept_id_high
        ORDER BY cr.created_at DESC
    """).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def search_related(concept_id: int, depth: int = 2) -> List[Dict]:
    """BFS traversal: find concepts within N hops via relationships.

    Returns all concepts reachable within `depth` hops, excluding the
    starting concept. Each result includes: id, title, mastery_level, hop_count.
    """
    if depth < 1:
        return []

    conn = _conn()
    rows = conn.execute(
        """
        WITH RECURSIVE neighborhood AS (
            -- Start node
            SELECT ? AS concept_id, 0 AS hops
            UNION ALL
            -- Walk edges (both directions)
            SELECT
                CASE WHEN cr.concept_id_low = n.concept_id
                     THEN cr.concept_id_high
                     ELSE cr.concept_id_low END AS concept_id,
                n.hops + 1 AS hops
            FROM neighborhood n
            JOIN concept_relations cr
                ON cr.concept_id_low = n.concept_id
                OR cr.concept_id_high = n.concept_id
            WHERE n.hops < ?
        )
        SELECT DISTINCT c.id, c.title, c.mastery_level, MIN(n.hops) AS hop_count
        FROM neighborhood n
        JOIN concepts c ON c.id = n.concept_id
        WHERE n.concept_id != ?
        GROUP BY c.id
        ORDER BY hop_count, c.title
    """,
        (concept_id, depth, concept_id),
    ).fetchall()
    conn.close()

    return [dict(r) for r in rows]
