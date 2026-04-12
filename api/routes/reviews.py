"""Review history and action-log endpoints."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

import db
from api.auth import verify_token

router = APIRouter()


def _parse_action_time_filter(time_filter: str) -> datetime | None:
    normalized = (time_filter or "all").strip().lower()
    if normalized == "all":
        return None
    if normalized == "today":
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if normalized == "7d":
        return datetime.now() - timedelta(days=7)
    if normalized == "30d":
        return datetime.now() - timedelta(days=30)
    raise HTTPException(status_code=400, detail="Invalid time filter")


@router.get("/api/reviews", dependencies=[Depends(verify_token)])
async def get_reviews(
    concept_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get review history for one concept or the global recent review log."""
    if concept_id is None:
        return db.get_recent_reviews_all(limit=limit)
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
    q: str | None = None,
    search: str | None = None,
    time: str = "all",
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    """Audit log with optional filters and pagination."""
    since = _parse_action_time_filter(time)
    search_text = (search if search is not None else q) or None
    offset = (page - 1) * per_page
    items = db.get_action_log(
        limit=per_page,
        offset=offset,
        action_filter=action,
        source_filter=source,
        since=since,
        search=search_text,
    )
    total = db.get_action_log_count(
        action_filter=action,
        source_filter=source,
        since=since,
        search=search_text,
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


@router.get("/api/actions/filters", dependencies=[Depends(verify_token)])
async def get_action_filters():
    """Distinct action and source values for action-log filters."""
    return {
        "actions": db.get_distinct_actions(),
        "sources": db.get_distinct_sources(),
    }
