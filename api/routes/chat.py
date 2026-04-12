"""Chat endpoints — conversational learning pipeline."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

import db
from api.auth import verify_token
from api.schemas import ChatActionRequest, ChatRequest, ChatResponse, ConfirmRequest
from services import state
from services.chat_session import (
    confirm_chat_action,
    decline_chat_action,
    handle_chat_action,
    handle_chat_message,
)

logger = logging.getLogger("api")

router = APIRouter()


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/api/chat/bootstrap", dependencies=[Depends(verify_token)])
async def chat_bootstrap():
    """Bootstrap payload for the web chat frontend."""
    return {
        "history": db.get_chat_history(limit=30),
        "commands": [
            {"label": "Review", "command": "/review"},
            {"label": "Due", "command": "/due"},
            {"label": "Topics", "command": "/topics"},
            {"label": "Maintain", "command": "/maintain"},
            {"label": "Reorganize", "command": "/reorganize"},
            {"label": "Preference", "command": "/preference "},
        ],
    }


@router.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    """Send a message to the learning agent using the shared chat controller."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        async with state.pipeline_serialized():
            payload = await handle_chat_message(req.message.strip(), author="solo_user", source="api")
            return payload
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/stream", dependencies=[Depends(verify_token)])
async def chat_stream(req: ChatRequest):
    """Stream chat status and the final response envelope over SSE."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async def event_stream():
        yield _sse_event("status", {"message": "Waiting for the learning agent..."})
        try:
            async with state.pipeline_serialized():
                payload = await handle_chat_message(req.message.strip(), author="solo_user", source="api")
            yield _sse_event("done", payload)
        except Exception as e:
            logger.exception("Chat stream endpoint error")
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/chat/confirm", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def confirm_action(req: ConfirmRequest):
    """Confirm a pending action from /api/chat using the shared chat controller."""

    try:
        async with state.pipeline_serialized():
            payload = await confirm_chat_action(req.action_data, source="api")
            return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Confirm endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/decline", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def decline_action(req: ConfirmRequest):
    """Decline a pending action from /api/chat using the shared chat controller."""
    try:
        async with state.pipeline_serialized():
            payload = await decline_chat_action(req.action_data, source="api")
            return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Decline endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/action", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def run_chat_action(req: ChatActionRequest):
    """Run a structured chat UI action such as quiz navigation or skip."""
    try:
        async with state.pipeline_serialized():
            payload = await handle_chat_action(req.action, author="solo_user", source="api")
            return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Chat action endpoint error")
        raise HTTPException(status_code=500, detail=str(e))
