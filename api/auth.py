"""Bearer token authentication dependency for FastAPI routes."""

from collections.abc import AsyncGenerator
import re

from fastapi import Header, HTTPException, Request

import config
from services import state


_API_USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def local_api_user_id() -> str:
    return state.get_local_user_id()


def _is_local_api_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return request.url.port == config.API_PORT and client_host in {
        "127.0.0.1",
        "::1",
        "localhost",
    }


def _resolve_api_user_id(requested_user: str | None) -> str:
    candidate = (requested_user or "").strip()
    if not candidate:
        return local_api_user_id()
    if not _API_USER_ID_RE.fullmatch(candidate):
        raise HTTPException(status_code=400, detail="Invalid X-Learning-User header")
    return candidate


async def verify_token(
    request: Request,
    authorization: str = Header(default=""),
    x_learning_user: str = Header(default=""),
) -> AsyncGenerator[str, None]:
    """Authenticate the request and bind the local API user scope for its lifetime."""
    user_id = _resolve_api_user_id(x_learning_user)
    if not config.API_SECRET_KEY:
        with state.current_user_scope(user_id):
            yield user_id
        return

    if not _is_local_api_request(request):
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Bearer token")
        token = authorization[len("Bearer ") :]
        if token != config.API_SECRET_KEY:
            raise HTTPException(status_code=401, detail="Invalid token")

    with state.current_user_scope(user_id):
        yield user_id
