"""Chat endpoints — conversational learning pipeline."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

import db
from services import pipeline, state
from services.parser import process_output, parse_llm_response
from services.tools import set_action_source

from api.auth import verify_token
from api.schemas import ChatRequest, ChatResponse, ConfirmRequest

logger = logging.getLogger("api")

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    """Send a message to the learning agent. Mirrors bot.py's _handle_user_message."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    state.last_activity_at = datetime.now()

    set_action_source('api')

    try:
        llm_response = await pipeline.call_with_fetch_loop(
            "command", req.message.strip(), "solo_user"
        )

        prefix, message, action_data = parse_llm_response(llm_response)
        if (action_data
                and action_data.get('action', '').lower().strip() == 'add_concept'):
            display_msg = action_data.get('message', message or '')
            return ChatResponse(
                type="pending_confirm",
                message=display_msg,
                pending_action=action_data,
            )

        final_result = await pipeline.execute_llm_response(
            req.message.strip(), llm_response, "command"
        )
        msg_type, message = process_output(final_result)
        return ChatResponse(type=msg_type, message=message)
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/confirm", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def confirm_action(req: ConfirmRequest):
    """Confirm a pending add_concept (or other intercepted action) from /api/chat."""
    from services.tools import execute_action
    set_action_source('api')

    action = req.action_data.get('action', '')
    params = req.action_data.get('params', {})
    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action' in action_data")

    try:
        msg_type, result = execute_action(action, params)
        display_msg = req.action_data.get('message', '')
        if msg_type == 'error':
            return ChatResponse(type="error", message=f"{display_msg}\n\n⚠️ {result}")
        else:
            return ChatResponse(type="reply", message=f"{display_msg}\n\n✅ {result}")
    except Exception as e:
        logger.exception("Confirm endpoint error")
        raise HTTPException(status_code=500, detail=str(e))
