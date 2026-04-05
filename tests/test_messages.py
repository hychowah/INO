"""Unit tests for bot.messages low-level helpers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.messages import send_long_with_view


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
