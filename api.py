"""
FastAPI backend for the Learning Agent mobile app.

Thin HTTP wrapper around the same pipeline that bot.py uses.
Run with: uvicorn api:app --host 0.0.0.0 --port 8080 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import config
import db
from services import pipeline
from services.parser import process_output, parse_llm_response
from services import state

logger = logging.getLogger("api")

# ============================================================================
# Startup / Shutdown
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize databases on startup."""
    pipeline.init_databases()
    logger.info("API started — databases initialized")
    yield

app = FastAPI(
    title="Learning Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins (React Native / Expo needs this)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Auth
# ============================================================================

async def verify_token(authorization: str = Header(default="")):
    """Simple bearer token check. Skipped if API_SECRET_KEY is not configured."""
    if not config.API_SECRET_KEY:
        return  # no auth configured — solo mode
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[len("Bearer "):]
    if token != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")

# ============================================================================
# Request / Response Models
# ============================================================================

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    type: str
    message: str
    pending_action: dict | None = None

# ============================================================================
# Request / Response Models — CRUD
# ============================================================================

class CreateConceptRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    topic_ids: list[int] | None = None
    topic_titles: list[str] | None = None

class UpdateConceptRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

class RemarkRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)

class CreateTopicRequest(BaseModel):
    title: str = Field(..., max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    parent_ids: list[int] | None = None

class UpdateTopicRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

class TopicLinkRequest(BaseModel):
    parent_id: int
    child_id: int

class CreateRelationRequest(BaseModel):
    concept_id_a: int
    concept_id_b: int
    relation_type: str = "builds_on"

class RemoveRelationRequest(BaseModel):
    concept_id_a: int
    concept_id_b: int

# ============================================================================
# Endpoints
# ============================================================================

@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    """Send a message to the learning agent. Mirrors bot.py's _handle_user_message."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    state.last_activity_at = __import__("datetime").datetime.now()

    # Set action source for audit trail
    from services.tools import set_action_source
    set_action_source('api')

    try:
        llm_response = await pipeline.call_with_fetch_loop(
            "command", req.message.strip(), "solo_user"
        )

        # Intercept add_concept — mirror bot.py's confirmation flow
        prefix, message, action_data = parse_llm_response(llm_response)
        if (action_data
                and action_data.get('action', '').lower().strip() == 'add_concept'):
            display_msg = action_data.get('message', message or '')
            return ChatResponse(
                type="pending_confirm",
                message=display_msg,
                pending_action=action_data,
            )

        final_result = await pipeline.execute_llm_response(
            req.message.strip(), llm_response, "command"
        )
        msg_type, message = process_output(final_result)
        return ChatResponse(type=msg_type, message=message)
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


class ConfirmRequest(BaseModel):
    action_data: dict


@app.post("/api/chat/confirm", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def confirm_action(req: ConfirmRequest):
    """Confirm a pending add_concept (or other intercepted action) from /api/chat."""
    from services.tools import execute_action, set_action_source
    set_action_source('api')

    action = req.action_data.get('action', '')
    params = req.action_data.get('params', {})
    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action' in action_data")

    try:
        msg_type, result = execute_action(action, params)
        display_msg = req.action_data.get('message', '')
        if msg_type == 'error':
            return ChatResponse(type="error", message=f"{display_msg}\n\n⚠️ {result}")
        else:
            return ChatResponse(type="reply", message=f"{display_msg}\n\n✅ {result}")
    except Exception as e:
        logger.exception("Confirm endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/topics", dependencies=[Depends(verify_token)])
async def get_topics():
    """Topic tree with mastery stats."""
    return db.get_hierarchical_topic_map()


@app.get("/api/topics/{topic_id}", dependencies=[Depends(verify_token)])
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


# ============================================================================
# Topic CRUD
# ============================================================================

@app.post("/api/topics", status_code=201, dependencies=[Depends(verify_token)])
async def create_topic(req: CreateTopicRequest):
    """Create a new learning topic."""
    from services.tools import set_action_source
    set_action_source('api')

    topic_id = db.add_topic(
        title=req.title,
        description=req.description,
        parent_ids=req.parent_ids,
    )
    return {"id": topic_id, "title": req.title, "message": f"Created topic '{req.title}'."}


@app.put("/api/topics/{topic_id}", dependencies=[Depends(verify_token)])
async def update_topic(topic_id: int, req: UpdateTopicRequest):
    """Update topic fields."""
    from services.tools import set_action_source
    set_action_source('api')

    existing = db.get_topic(topic_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Topic not found")

    fields = req.model_dump(exclude_unset=True)
    if fields:
        db.update_topic(topic_id, **fields)

    return db.get_topic(topic_id)


@app.delete("/api/topics/{topic_id}", dependencies=[Depends(verify_token)])
async def delete_topic(topic_id: int, force: bool = False):
    """Delete a topic. Returns 409 if it still has concepts or children unless force=True."""
    from services.tools import set_action_source
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


@app.post("/api/topics/link", dependencies=[Depends(verify_token)])
async def link_topics(req: TopicLinkRequest):
    """Create a parent→child relationship between two topics."""
    from services.tools import set_action_source
    set_action_source('api')

    if req.parent_id == req.child_id:
        raise HTTPException(status_code=400, detail="Cannot link a topic to itself")

    # Check if already linked (idempotent — not an error)
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


@app.post("/api/topics/unlink", dependencies=[Depends(verify_token)])
async def unlink_topics(req: TopicLinkRequest):
    """Remove a parent→child relationship between two topics."""
    from services.tools import set_action_source
    set_action_source('api')

    db.unlink_topics(req.parent_id, req.child_id)
    return {"message": f"Unlinked topic {req.child_id} from topic {req.parent_id}."}


# ============================================================================
# Concept CRUD
# ============================================================================

@app.get("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def get_concept(concept_id: int):
    """Concept detail with remarks and review history."""
    detail = db.get_concept_detail(concept_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Concept not found")
    return detail


@app.get("/api/concepts", dependencies=[Depends(verify_token)])
async def list_concepts(
    topic_id: int | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """List concepts with optional filtering and pagination."""
    if search:
        # FTS search — no offset support, return matching page
        all_items = db.search_concepts(query=search, limit=per_page * page)
        total = len(all_items)
        offset = (page - 1) * per_page
        items = all_items[offset:offset + per_page]
    elif topic_id is not None:
        all_items = db.get_concepts_for_topic(topic_id)
        total = len(all_items)
        offset = (page - 1) * per_page
        items = all_items[offset:offset + per_page]
    else:
        all_items = db.get_all_concepts_with_topics()
        total = len(all_items)
        offset = (page - 1) * per_page
        items = all_items[offset:offset + per_page]

    return {"items": items, "total": total, "page": page, "per_page": per_page}


@app.post("/api/concepts", status_code=201, dependencies=[Depends(verify_token)])
async def create_concept(req: CreateConceptRequest):
    """Create a new concept under one or more topics."""
    from services.tools import set_action_source
    set_action_source('api')

    # Duplicate check
    existing = db.find_concept_by_title(req.title)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Concept already exists with id {existing['id']}",
        )

    # Resolve topic_titles to IDs (exact match or create)
    topic_ids = list(req.topic_ids) if req.topic_ids else []
    if req.topic_titles:
        for title in req.topic_titles:
            found = db.find_topic_by_title(title)
            if found:
                topic_ids.append(found['id'])
            else:
                new_id = db.add_topic(title=title)
                topic_ids.append(new_id)

    concept_id = db.add_concept(
        title=req.title,
        description=req.description,
        topic_ids=topic_ids or None,
    )
    return {"id": concept_id, "title": req.title, "message": f"Created concept '{req.title}'."}


@app.put("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def update_concept(concept_id: int, req: UpdateConceptRequest):
    """Update concept fields (title, description)."""
    from services.tools import set_action_source
    set_action_source('api')

    existing = db.get_concept(concept_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Concept not found")

    fields = req.model_dump(exclude_unset=True)
    if fields:
        db.update_concept(concept_id, **fields)

    return db.get_concept(concept_id)


@app.delete("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def delete_concept(concept_id: int):
    """Delete a concept and all its relations, remarks, and review logs."""
    from services.tools import set_action_source
    set_action_source('api')

    if not db.delete_concept(concept_id):
        raise HTTPException(status_code=404, detail="Concept not found")
    return {"message": f"Concept {concept_id} deleted."}


@app.post("/api/concepts/{concept_id}/remarks", status_code=201, dependencies=[Depends(verify_token)])
async def add_remark(concept_id: int, req: RemarkRequest):
    """Add a remark (note) to a concept."""
    from services.tools import set_action_source
    set_action_source('api')

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


# ============================================================================
# Relations
# ============================================================================

@app.get("/api/concepts/{concept_id}/relations", dependencies=[Depends(verify_token)])
async def get_concept_relations(concept_id: int):
    """Get all relationships for a concept."""
    existing = db.get_concept(concept_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Concept not found")
    return db.get_relations(concept_id)


@app.post("/api/relations", status_code=201, dependencies=[Depends(verify_token)])
async def create_relation(req: CreateRelationRequest):
    """Create a relationship between two concepts."""
    from services.tools import set_action_source
    set_action_source('api')

    if req.relation_type not in db.VALID_RELATION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid relation_type. Must be one of: {', '.join(sorted(db.VALID_RELATION_TYPES))}",
        )

    relation_id = db.add_relation(req.concept_id_a, req.concept_id_b, req.relation_type)
    if relation_id is None:
        raise HTTPException(
            status_code=400,
            detail="Relation rejected (duplicate, cap exceeded, self-referential, or invalid concept IDs)",
        )
    return {"id": relation_id}


@app.post("/api/relations/remove", dependencies=[Depends(verify_token)])
async def remove_relation(req: RemoveRelationRequest):
    """Remove a relationship between two concepts."""
    from services.tools import set_action_source
    set_action_source('api')

    db.remove_relation(req.concept_id_a, req.concept_id_b)
    return {"message": "Relation removed."}


# ============================================================================
# Reviews & Logs
# ============================================================================

@app.get("/api/reviews", dependencies=[Depends(verify_token)])
async def get_reviews(
    concept_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get review history for a concept."""
    if concept_id is None:
        raise HTTPException(status_code=400, detail="concept_id query parameter is required")
    return db.get_recent_reviews(concept_id, limit=limit)


@app.get("/api/reviews/next", dependencies=[Depends(verify_token)])
async def get_next_review():
    """Get the next concept due for review (nearest next_review_at)."""
    return db.get_next_review_concept()


@app.get("/api/actions", dependencies=[Depends(verify_token)])
async def get_actions(
    action: str | None = None,
    source: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """Audit log with optional filters and pagination."""
    offset = (page - 1) * per_page
    items = db.get_action_log(
        limit=per_page,
        offset=offset,
        action_filter=action,
        source_filter=source,
    )
    total = db.get_action_log_count(
        action_filter=action,
        source_filter=source,
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


# ============================================================================
# Graph
# ============================================================================

@app.get("/api/graph", dependencies=[Depends(verify_token)])
async def get_graph(
    topic_id: int | None = None,
    min_mastery: int | None = None,
    max_mastery: int | None = None,
    max_nodes: int = Query(default=500, le=2000),
):
    """Knowledge graph: concept nodes, topic nodes, and all edges.
    Optional filters for scalability."""
    concepts = db.get_all_concepts_summary()

    # Server-side filtering
    if topic_id is not None:
        concepts = [c for c in concepts if topic_id in c.get('topic_ids', [])]
    if min_mastery is not None:
        concepts = [c for c in concepts if (c.get('mastery_level') or 0) >= min_mastery]
    if max_mastery is not None:
        concepts = [c for c in concepts if (c.get('mastery_level') or 0) <= max_mastery]

    # Cap node count (prioritize by mastery — most reviewed concepts)
    total_concepts = len(concepts)
    if len(concepts) > max_nodes:
        concepts = sorted(concepts, key=lambda c: c.get('mastery_level') or 0, reverse=True)[:max_nodes]

    concept_ids = {c['id'] for c in concepts}

    # Filter edges to only include visible concepts
    all_relations = db.get_all_relations()
    concept_edges = [
        e for e in all_relations
        if e['concept_id_low'] in concept_ids and e['concept_id_high'] in concept_ids
    ]

    all_ct_edges = db.get_concept_topic_edges()
    ct_edges = [e for e in all_ct_edges if e['concept_id'] in concept_ids]

    return {
        "concept_nodes": concepts,
        "topic_nodes": db.get_all_topics(),
        "concept_edges": concept_edges,
        "topic_edges": db.get_topic_relations(),
        "concept_topic_edges": ct_edges,
        "total_concepts": total_concepts,
    }


# ============================================================================
# Due / Stats / Health
# ============================================================================

@app.get("/api/due", dependencies=[Depends(verify_token)])
async def get_due(limit: int = 10):
    """Concepts due for review."""
    return db.get_due_concepts(limit=limit)


@app.get("/api/stats", dependencies=[Depends(verify_token)])
async def get_stats():
    """Aggregate review statistics."""
    return db.get_review_stats()


@app.get("/api/health")
async def health():
    """Health check (no auth required)."""
    return {"status": "ok"}


# ============================================================================
# Persona
# ============================================================================

class PersonaRequest(BaseModel):
    name: str


@app.get("/api/persona", dependencies=[Depends(verify_token)])
async def get_persona_endpoint():
    """Get current persona and available presets."""
    return {
        "current": db.get_persona(),
        "available": db.get_available_personas(),
    }


@app.post("/api/persona", dependencies=[Depends(verify_token)])
async def set_persona_endpoint(req: PersonaRequest):
    """Switch persona preset."""
    try:
        db.set_persona(req.name.strip().lower())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Invalidate prompt cache + session so new persona takes effect
    pipeline.invalidate_prompt_cache()
    pipeline.reset_conversation_session()

    return {"current": db.get_persona(), "message": f"Switched to {req.name} persona."}


# ============================================================================
# Run directly: python api.py
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    uvicorn.run(
        "api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
    )
