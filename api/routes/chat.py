"""Chat endpoints — conversational learning pipeline."""

import logging

from fastapi import APIRouter, Depends, HTTPException

import db
from api.auth import verify_token
from api.schemas import ChatActionRequest, ChatRequest, ChatResponse, ConfirmRequest
from services import state
from services.chat_session import (
    confirm_webui_action,
    decline_webui_action,
    handle_webui_action,
    handle_webui_message,
)

logger = logging.getLogger("api")

router = APIRouter()


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
    """Send a message to the learning agent using the shared web chat backend."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        async with state.pipeline_serialized():
            payload = await handle_webui_message(req.message.strip(), author="solo_user", source="api")
            return payload
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/confirm", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def confirm_action(req: ConfirmRequest):
    """Confirm a pending action from /api/chat using the shared web chat backend."""

    try:
        async with state.pipeline_serialized():
            payload = await confirm_webui_action(req.action_data, source="api")
            return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Confirm endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/decline", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def decline_action(req: ConfirmRequest):
    """Decline a pending action from /api/chat using the shared web chat backend."""
    try:
        async with state.pipeline_serialized():
            payload = await decline_webui_action(req.action_data, source="api")
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
            payload = await handle_webui_action(req.action, author="solo_user", source="api")
            return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Chat action endpoint error")
        raise HTTPException(status_code=500, detail=str(e))
