"""Concept relation (graph edge) endpoints."""

from fastapi import APIRouter, Depends, HTTPException

import db
from services.tools import set_action_source

from api.auth import verify_token
from api.schemas import CreateRelationRequest, RemoveRelationRequest

router = APIRouter()


@router.post("/api/relations", status_code=201, dependencies=[Depends(verify_token)])
async def create_relation(req: CreateRelationRequest):
    """Create a relationship between two concepts."""
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


@router.post("/api/relations/remove", dependencies=[Depends(verify_token)])
async def remove_relation(req: RemoveRelationRequest):
    """Remove a relationship between two concepts."""
    set_action_source('api')

    db.remove_relation(req.concept_id_a, req.concept_id_b)
    return {"message": "Relation removed."}
