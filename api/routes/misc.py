"""Due/stats/health/persona endpoints."""

from fastapi import APIRouter, Depends, HTTPException

import db
from api.auth import verify_token
from api.schemas import PersonaRequest
from services import pipeline

router = APIRouter()


@router.get("/api/due", dependencies=[Depends(verify_token)])
async def get_due(limit: int = 10):
    """Concepts due for review."""
    return db.get_due_concepts(limit=limit)


@router.get("/api/stats", dependencies=[Depends(verify_token)])
async def get_stats():
    """Aggregate review statistics."""
    return db.get_review_stats()


@router.get("/api/health")
async def health():
    """Health check (no auth required)."""
    return {"status": "ok"}


@router.get("/api/persona", dependencies=[Depends(verify_token)])
async def get_persona_endpoint():
    """Get current persona and available presets."""
    return {
        "current": db.get_persona(),
        "available": db.get_available_personas(),
    }


@router.post("/api/persona", dependencies=[Depends(verify_token)])
async def set_persona_endpoint(req: PersonaRequest):
    """Switch persona preset."""
    try:
        db.set_persona(req.name.strip().lower())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pipeline.invalidate_prompt_cache()
    pipeline.reset_conversation_session()

    return {"current": db.get_persona(), "message": f"Switched to {req.name} persona."}
