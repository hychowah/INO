from unittest.mock import AsyncMock

import db
import pytest

from services.learn_turn import run_learn_turn


@pytest.mark.anyio
async def test_run_learn_turn_uses_reply_mode_when_single_quiz_active(test_db):
    del test_db
    db.set_session("quiz_anchor_concept_id", "42")
    db.set_session("last_quiz_question", "What happens to induced drag?")

    call_with_fetch_loop = AsyncMock(return_value="REPLY: raw")
    execute_response = AsyncMock(return_value="REPLY: final")

    result = await run_learn_turn(
        "it gets cut in half",
        "test-user",
        source="discord",
        call_with_fetch_loop=call_with_fetch_loop,
        parse_response=lambda _raw: ("REPLY", "raw", None),
        execute_response=execute_response,
        process_output=lambda output: ("reply", output.removeprefix("REPLY: ").strip()),
    )

    assert result.msg_type == "reply"
    assert call_with_fetch_loop.await_args.args[0] == "reply"
    assert execute_response.await_args.args[2] == "reply"


@pytest.mark.anyio
async def test_run_learn_turn_uses_command_mode_without_active_quiz(test_db):
    del test_db
    db.set_session("quiz_anchor_concept_id", None)
    db.set_session("active_concept_ids", None)

    call_with_fetch_loop = AsyncMock(return_value="REPLY: raw")
    execute_response = AsyncMock(return_value="REPLY: final")

    result = await run_learn_turn(
        "teach me about GraphRAG",
        "test-user",
        source="discord",
        call_with_fetch_loop=call_with_fetch_loop,
        parse_response=lambda _raw: ("REPLY", "raw", None),
        execute_response=execute_response,
        process_output=lambda output: ("reply", output.removeprefix("REPLY: ").strip()),
    )

    assert result.msg_type == "reply"
    assert call_with_fetch_loop.await_args.args[0] == "command"
    assert execute_response.await_args.args[2] == "command"