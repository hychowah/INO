"""Topic CRUD and hierarchy endpoints."""

from fastapi import APIRouter, Depends, HTTPException

import db
from services.tools import set_action_source

from api.auth import verify_token
from api.schemas import CreateTopicRequest, UpdateTopicRequest, TopicLinkRequest

router = APIRouter()


@router.get("/api/topics", dependencies=[Depends(verify_token)])
async def get_topics():
    """Topic tree with mastery stats."""
    return db.get_hierarchical_topic_map()


@router.get("/api/topics/{topic_id}", dependencies=[Depends(verify_token)])
async def get_topic(topic_id: int):
    """Topic detail with concepts."""
    topic = db.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    concepts = db.get_concepts_for_topic(topic_id)
    children = db.get_topic_children(topic_id)
    parents = db.get_topic_parents(topic_id)

    return {
        **topic,
        "concepts": concepts,
        "children": children,
        "parents": parents,
    }


@router.post("/api/topics", status_code=201, dependencies=[Depends(verify_token)])
async def create_topic(req: CreateTopicRequest):
    """Create a new learning topic."""
    set_action_source('api')

    topic_id = db.add_topic(
        title=req.title,
        description=req.description,
        parent_ids=req.parent_ids,
    )
    return {"id": topic_id, "title": req.title, "message": f"Created topic '{req.title}'."}


@router.put("/api/topics/{topic_id}", dependencies=[Depends(verify_token)])
async def update_topic(topic_id: int, req: UpdateTopicRequest):
    """Update topic fields."""
    set_action_source('api')

    existing = db.get_topic(topic_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Topic not found")

    fields = req.model_dump(exclude_unset=True)
    if fields:
        db.update_topic(topic_id, **fields)

    return db.get_topic(topic_id)


@router.delete("/api/topics/{topic_id}", dependencies=[Depends(verify_token)])
async def delete_topic(topic_id: int, force: bool = False):
    """Delete a topic. Returns 409 if it still has concepts or children unless force=True."""
    set_action_source('api')

    topic = db.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not force:
        concepts = db.get_concepts_for_topic(topic_id)
        if concepts:
            raise HTTPException(
                status_code=409,
                detail=f"Topic still has {len(concepts)} concept(s). "
                       f"Unlink them first, or use ?force=true.",
            )
        children = db.get_topic_children(topic_id)
        if children:
            raise HTTPException(
                status_code=409,
                detail=f"Topic still has {len(children)} child topic(s). "
                       f"Unlink them first, or use ?force=true.",
            )

    db.delete_topic(topic_id)
    return {"message": f"Topic {topic_id} deleted."}


@router.post("/api/topics/link", dependencies=[Depends(verify_token)])
async def link_topics(req: TopicLinkRequest):
    """Create a parent→child relationship between two topics."""
    set_action_source('api')

    if req.parent_id == req.child_id:
        raise HTTPException(status_code=400, detail="Cannot link a topic to itself")

    children = db.get_topic_children(req.parent_id)
    if any(c['id'] == req.child_id for c in children):
        return {"message": "Already linked."}

    success = db.link_topics(req.parent_id, req.child_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cycle detected — this link would create a circular dependency",
        )
    return {"message": f"Linked topic {req.child_id} under topic {req.parent_id}."}


@router.post("/api/topics/unlink", dependencies=[Depends(verify_token)])
async def unlink_topics(req: TopicLinkRequest):
    """Remove a parent→child relationship between two topics."""
    set_action_source('api')

    db.unlink_topics(req.parent_id, req.child_id)
    return {"message": f"Unlinked topic {req.child_id} from topic {req.parent_id}."}
