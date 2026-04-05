"""Knowledge graph endpoint."""

from fastapi import APIRouter, Depends, Query

import db
from api.auth import verify_token

router = APIRouter()


@router.get("/api/graph", dependencies=[Depends(verify_token)])
async def get_graph(
    topic_id: int | None = None,
    min_mastery: int | None = None,
    max_mastery: int | None = None,
    max_nodes: int = Query(default=500, le=2000),
):
    """Knowledge graph: concept nodes, topic nodes, and all edges.
    Optional filters for scalability."""
    concepts = db.get_all_concepts_summary()

    if topic_id is not None:
        concepts = [c for c in concepts if topic_id in c.get("topic_ids", [])]
    if min_mastery is not None:
        concepts = [c for c in concepts if (c.get("mastery_level") or 0) >= min_mastery]
    if max_mastery is not None:
        concepts = [c for c in concepts if (c.get("mastery_level") or 0) <= max_mastery]

    total_concepts = len(concepts)
    if len(concepts) > max_nodes:
        concepts = sorted(concepts, key=lambda c: c.get("mastery_level") or 0, reverse=True)[
            :max_nodes
        ]

    concept_ids = {c["id"] for c in concepts}

    all_relations = db.get_all_relations()
    concept_edges = [
        e
        for e in all_relations
        if e["concept_id_low"] in concept_ids and e["concept_id_high"] in concept_ids
    ]

    all_ct_edges = db.get_concept_topic_edges()
    ct_edges = [e for e in all_ct_edges if e["concept_id"] in concept_ids]

    return {
        "concept_nodes": concepts,
        "topic_nodes": db.get_all_topics(),
        "concept_edges": concept_edges,
        "topic_edges": db.get_topic_relations(),
        "concept_topic_edges": ct_edges,
        "total_concepts": total_concepts,
    }
