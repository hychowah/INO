"""Review history and action-log endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

import db
from api.auth import verify_token

router = APIRouter()


@router.get("/api/reviews", dependencies=[Depends(verify_token)])
async def get_reviews(
    concept_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get review history for a concept."""
    if concept_id is None:
        raise HTTPException(status_code=400, detail="concept_id query parameter is required")
    return db.get_recent_reviews(concept_id, limit=limit)


@router.get("/api/reviews/next", dependencies=[Depends(verify_token)])
async def get_next_review():
    """Get the next concept due for review (nearest next_review_at)."""
    return db.get_next_review_concept()


@router.get("/api/forecast", dependencies=[Depends(verify_token)])
async def get_forecast(range: str = "weeks"):
    """Legacy forecast payload used by the current webui page."""
    try:
        return db.get_due_forecast(range)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/forecast/concepts", dependencies=[Depends(verify_token)])
async def get_forecast_concepts(range: str = "weeks", bucket: str = "0"):
    """Legacy forecast bucket detail payload used by the current webui page."""
    try:
        return db.get_forecast_bucket_concepts(range, bucket)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/actions", dependencies=[Depends(verify_token)])
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
