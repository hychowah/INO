"""Unit tests for bot.messages helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import db
from bot.messages import send_long_with_view, send_review_question
from services.parser import CONTROLLED_FORMAT_FAILURE_MESSAGE
from services.views import QuizQuestionView


@pytest.mark.anyio
async def test_send_long_with_view_omits_view_kwarg_when_none():
    """send_long_with_view must NOT forward view=None to send_fn.

    Discord's Webhook/ctx.send rejects view=None explicitly — the kwarg
    must be omitted entirely when there is no view to attach.
    """
    send_fn = AsyncMock(return_value=MagicMock())
    await send_long_with_view(send_fn, "hello", view=None)
    send_fn.assert_awaited_once_with("hello")


@pytest.mark.anyio
async def test_send_long_with_view_passes_view_kwarg_when_provided():
    """send_long_with_view must forward view= to send_fn when a view is given."""
    send_fn = AsyncMock(return_value=MagicMock())
    fake_view = MagicMock()
    await send_long_with_view(send_fn, "hello", view=fake_view)
    send_fn.assert_awaited_once_with("hello", view=fake_view)


@pytest.mark.anyio
async def test_send_long_with_view_blocks_machine_artifacts():
    send_fn = AsyncMock(return_value=MagicMock())
    raw = 'The user is answering.\n```json\n{"action":"assess","params":{}}\n```'

    await send_long_with_view(send_fn, raw, view=None)

    send_fn.assert_awaited_once_with(CONTROLLED_FORMAT_FAILURE_MESSAGE)


@pytest.mark.anyio
async def test_send_review_question_attaches_skip_button_at_boundary(test_db):
    cid = db.add_concept("Boundary Review", "Desc")
    db.update_concept(cid, review_count=2)
    send_fn = AsyncMock(return_value=MagicMock())
    mock_send_long_with_view = AsyncMock(return_value=MagicMock())

    async def fake_handler(_text, _author):
        return "ignored", None, None, None

    with patch("bot.messages.send_long_with_view", new=mock_send_long_with_view):
        await send_review_question(send_fn, "What is the boundary?", cid, fake_handler)

    send_fn.assert_not_awaited()
    mock_send_long_with_view.assert_awaited_once()
    call = mock_send_long_with_view.await_args
    assert call.args[0] is send_fn
    assert call.args[1] == (
        "📚 **Learning Review**\nWhat is the boundary?\n\n"
        "📖 **Boundary Review** · Score: 0/100 · Review #3"
    )
    assert isinstance(call.kwargs["view"], QuizQuestionView)
    assert call.kwargs["view"].concept_id == cid
