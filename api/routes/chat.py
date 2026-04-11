"""Chat endpoints — conversational learning pipeline."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

import db
from api.auth import verify_token
from api.schemas import ChatRequest, ChatResponse, ConfirmRequest
from services import pipeline, state
from services.chat_actions import (
    API_CONFIRMABLE_ACTIONS,
    confirmation_history_entry,
    decline_history_entry,
    is_intercepted_action,
    require_confirmable_action,
)
from services.parser import parse_llm_response, process_output
from services.tools import set_action_source

logger = logging.getLogger("api")

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def chat(req: ChatRequest):
    """Send a message to the learning agent. Mirrors bot.py's _handle_user_message."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        async with state.pipeline_serialized():
            state.last_activity_at = datetime.now()
            set_action_source("api")

            llm_response = await pipeline.call_with_fetch_loop(
                "command", req.message.strip(), "solo_user"
            )

            prefix, message, action_data = parse_llm_response(llm_response)
            if action_data and is_intercepted_action(action_data):
                display_msg = action_data.get("message", message or "")
                db.add_chat_message("user", req.message.strip())
                if display_msg:
                    db.add_chat_message("assistant", display_msg)
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
    from services.tools import execute_action, execute_suggest_topic_accept

    action = req.action_data.get("action", "")
    params = req.action_data.get("params", {})
    try:
        # Whitelist: only user-confirmation flows are allowed through this endpoint.
        # Actions that mutate scores (assess, multi_assess) must go through the
        # full pipeline so the quiz-active guard and audit trail apply correctly.
        action = require_confirmable_action(
            req.action_data,
            API_CONFIRMABLE_ACTIONS,
            "confirmed via this endpoint",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        async with state.pipeline_serialized():
            set_action_source("api")
            display_msg = req.action_data.get("message", "")
            if action == "suggest_topic":
                success, summary, _topic_id = execute_suggest_topic_accept(req.action_data)
                if not success:
                    return ChatResponse(type="error", message=f"{display_msg}\n\n⚠️ {summary}")
                db.add_chat_message("user", confirmation_history_entry(req.action_data))
                db.add_chat_message("assistant", summary)
                return ChatResponse(type="reply", message=f"{display_msg}\n\n{summary}")

            msg_type, result = execute_action(action, params)
            if msg_type == "error":
                return ChatResponse(type="error", message=f"{display_msg}\n\n⚠️ {result}")

            db.add_chat_message("user", confirmation_history_entry(req.action_data))
            db.add_chat_message("assistant", f"✅ {result}")
            return ChatResponse(type="reply", message=f"{display_msg}\n\n✅ {result}")
    except Exception as e:
        logger.exception("Confirm endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/chat/decline", response_model=ChatResponse, dependencies=[Depends(verify_token)])
async def decline_action(req: ConfirmRequest):
    """Decline a pending add_concept or suggest_topic from /api/chat."""
    try:
        async with state.pipeline_serialized():
            set_action_source("api")
            require_confirmable_action(
                req.action_data,
                API_CONFIRMABLE_ACTIONS,
                "declined via this endpoint",
            )
            entry = decline_history_entry(req.action_data)
            db.add_chat_message("user", entry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ChatResponse(type="reply", message="Declined.")
