"""Discord message helpers — splitting long text and sending with views."""

from typing import Awaitable, Callable

import discord

import config
import db
from services.formatting import format_quiz_metadata
from services.parser import guard_user_message
from services.views import QuizQuestionView, should_show_quiz_skip_button


def _split_message(text: str, limit: int = config.MAX_MESSAGE_LENGTH) -> list[str]:
    """Split text into chunks, preferring newline boundaries."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        search_start = max(0, limit - 200)
        newline_pos = text.rfind("\n", search_start, limit)
        if newline_pos > 0:
            chunks.append(text[:newline_pos])
            text = text[newline_pos + 1 :]
        else:
            chunks.append(text[:limit])
            text = text[limit:]
    return chunks


async def send_long(ctx, text: str, title: str = "Learn"):
    """Send text to Discord, handling length limits."""
    is_interaction = ctx.interaction is not None

    if not text or not text.strip():
        text = "(empty response)"
    text = guard_user_message(text)

    chunks = _split_message(text)

    for chunk in chunks:
        if is_interaction:
            await ctx.interaction.followup.send(chunk)
        else:
            await ctx.send(chunk)


async def send_long_with_view(send_fn, text: str, view=None) -> "discord.Message":
    """Send a long message with a Discord view (buttons) on the last chunk."""
    if not text or not text.strip():
        text = "(empty response)"
    text = guard_user_message(text)

    chunks = _split_message(text)

    for chunk in chunks[:-1]:
        await send_fn(chunk)

    if view is not None:
        sent = await send_fn(chunks[-1], view=view)
    else:
        sent = await send_fn(chunks[-1])
    return sent


async def send_review_question(
    send_fn, question: str, concept_id: int | None, message_handler: Callable[..., Awaitable]
) -> "discord.Message":
    """Send a review question and attach the skip button when eligible."""
    view = None
    concept = None

    if concept_id is not None:
        concept = db.get_concept(concept_id)
        if should_show_quiz_skip_button(concept):
            view = QuizQuestionView(
                concept_id=concept_id,
                message_handler=message_handler,
                show_skip=True,
            )

    meta = format_quiz_metadata(concept)
    meta_suffix = f"\n\n{meta}" if meta else ""
    return await send_long_with_view(
        send_fn, f"📚 **Learning Review**\n{question}{meta_suffix}", view=view
    )
