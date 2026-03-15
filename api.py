"""
FastAPI backend for the Learning Agent mobile app.

Thin HTTP wrapper around the same pipeline that bot.py uses.
Run with: uvicorn api:app --host 0.0.0.0 --port 8080 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
import db
from services import pipeline
from services.parser import process_output
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

# ============================================================================
# Endpoints
# ============================================================================

@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    """Send a message to the learning agent. Mirrors bot.py's _handle_user_message."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    state.last_activity_at = __import__("datetime").datetime.now()

    try:
        llm_response = await pipeline.call_with_fetch_loop(
            "command", req.message.strip(), "solo_user"
        )
        final_result = await pipeline.execute_llm_response(
            req.message.strip(), llm_response, "command"
        )
        msg_type, message = process_output(final_result)
        return ChatResponse(type=msg_type, message=message)
    except Exception as e:
        logger.exception("Chat endpoint error")
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


@app.get("/api/concepts/{concept_id}", dependencies=[Depends(verify_token)])
async def get_concept(concept_id: int):
    """Concept detail with remarks and review history."""
    detail = db.get_concept_detail(concept_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Concept not found")
    return detail


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
