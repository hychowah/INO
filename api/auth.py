"""Bearer token authentication dependency for FastAPI routes."""

from fastapi import HTTPException, Header

import config


async def verify_token(authorization: str = Header(default="")) -> None:
    """Simple bearer token check. Skipped if API_SECRET_KEY is not configured."""
    if not config.API_SECRET_KEY:
        return  # no auth configured — solo mode
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[len("Bearer "):]
    if token != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
