"""Concept CRUD endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

import db
from api.auth import verify_token
from api.schemas import (
    CreateConceptRequest,
    RemarkRequest,
    UpdateConceptRequest,
)
from services.tools import set_action_source

router = APIRouter()

_CONCEPT_SORT_FIELDS = {
    "id",
    "title",
    "mastery_level",
    "interval_days",
    "review_count",
    "next_review_at",
    "last_reviewed_at",
}


def _normalize_concept_list_item(
    item: dict,
    topic_lookup: dict[int, dict],
    topic_id_hint: int | None = None,
) -> dict:
    normalized = dict(item)
    normalized["latest_remark"] = normalized.get("latest_remark") or normalized.get("remark_summary")

    if "topics" in normalized and isinstance(normalized["topics"], list):
        normalized["topic_ids"] = [int(topic["id"]) for topic in normalized["topics"] if "id" in topic]
        return normalized

    topic_ids = normalized.get("topic_ids")
    if not topic_ids:
        concept = db.get_concept(normalized["id"])
        topic_ids = concept.get("topic_ids", []) if concept else ([] if topic_id_hint is None else [topic_id_hint])

    normalized["topic_ids"] = [int(topic_id) for topic_id in topic_ids]
    normalized["topics"] = [
        {"id": topic_id, "title": topic_lookup[topic_id]["title"]}
        for topic_id in normalized["topic_ids"]
        if topic_id in topic_lookup
    ]
    return normalized


def _concept_sort_value(item: dict, field: str):
    value = item.get(field)
    if field in {"next_review_at", "last_reviewed_at"}:
        if not value:
            return datetime.max
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if field == "title":
        return str(value or "").lower()
    return value if value is not None else -1


@router.get("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def get_concept(concept_id: int):
    """Concept detail with remarks and review history."""
    detail = db.get_concept_detail(concept_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Concept not found")
    return detail


@router.get("/api/concepts", dependencies=[Depends(verify_token)])
async def list_concepts(
    topic_id: int | None = None,
    search: str | None = None,
    sort: str | None = None,
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """List concepts with optional filtering and pagination."""
    if sort and sort not in _CONCEPT_SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unsupported sort field '{sort}'")

    if search:
        all_items = db.search_concepts(query=search, limit=per_page * page)
    elif topic_id is not None:
        all_items = db.get_concepts_for_topic(topic_id)
    else:
        all_items = db.get_all_concepts_with_topics()

    topic_lookup = {topic["id"]: topic for topic in db.get_all_topics()}
    normalized_items = [
        _normalize_concept_list_item(item, topic_lookup, topic_id_hint=topic_id)
        for item in all_items
    ]
    if sort:
        normalized_items.sort(key=lambda item: _concept_sort_value(item, sort), reverse=order == "desc")

    total = len(normalized_items)
    offset = (page - 1) * per_page
    items = normalized_items[offset : offset + per_page]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.post("/api/concepts", status_code=201, dependencies=[Depends(verify_token)])
async def create_concept(req: CreateConceptRequest):
    """Create a new concept under one or more topics."""
    set_action_source("api")

    existing = db.find_concept_by_title(req.title)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Concept already exists with id {existing['id']}",
        )

    topic_ids = list(req.topic_ids) if req.topic_ids else []
    if req.topic_titles:
        for title in req.topic_titles:
            found = db.find_topic_by_title(title)
            if found:
                topic_ids.append(found["id"])
            else:
                new_id = db.add_topic(title=title)
                topic_ids.append(new_id)

    concept_id = db.add_concept(
        title=req.title,
        description=req.description,
        topic_ids=topic_ids or None,
    )
    return {"id": concept_id, "title": req.title, "message": f"Created concept '{req.title}'."}


@router.put("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def update_concept(concept_id: int, req: UpdateConceptRequest):
    """Update concept fields (title, description)."""
    set_action_source("api")

    existing = db.get_concept(concept_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Concept not found")

    fields = req.model_dump(exclude_unset=True)
    if fields:
        db.update_concept(concept_id, **fields)

    return db.get_concept(concept_id)


@router.delete("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def delete_concept(concept_id: int):
    """Delete a concept and all its relations, remarks, and review logs."""
    set_action_source("api")

    if not db.delete_concept(concept_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    return {"message": f"Concept {concept_id} deleted."}


@router.post("/api/concept/{concept_id}/delete", dependencies=[Depends(verify_token)])
async def delete_concept_legacy(concept_id: int):
    """Legacy delete endpoint used by the current concepts page JS."""
    set_action_source("api")

    if not db.delete_concept(concept_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    return {"ok": True}


@router.post(
    "/api/concepts/{concept_id}/remarks", status_code=201, dependencies=[Depends(verify_token)]
)
async def add_remark(concept_id: int, req: RemarkRequest):
    """Add a remark (note) to a concept."""
    set_action_source("api")

    existing = db.get_concept(concept_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Concept not found")

    remark_id = db.add_remark(concept_id, req.content)
    return {
        "id": remark_id,
        "concept_id": concept_id,
        "content": req.content,
        "remark_summary": db.get_latest_remark(concept_id),
    }


@router.get("/api/concepts/{concept_id}/relations", dependencies=[Depends(verify_token)])
async def get_concept_relations(concept_id: int):
    """Get all relationships for a concept."""
    existing = db.get_concept(concept_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Concept not found")
    return db.get_relations(concept_id)
