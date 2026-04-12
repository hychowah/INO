"""Bearer token authentication dependency for FastAPI routes."""

from fastapi import Header, HTTPException, Request

import config


def _is_local_api_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return request.url.port == config.API_PORT and client_host in {
        "127.0.0.1",
        "::1",
        "localhost",
    }


async def verify_token(request: Request, authorization: str = Header(default="")) -> None:
    """Simple bearer token check. Skipped if API_SECRET_KEY is not configured."""
    if not config.API_SECRET_KEY:
        return  # no auth configured — solo mode
    if _is_local_api_request(request):
        return
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[len("Bearer ") :]
    if token != config.API_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
