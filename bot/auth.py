"""Authorization decorator for restricting commands to the configured user."""

import logging

from discord.ext import commands

import config

logger = logging.getLogger("bot")


def authorized_only():
    """Decorator to restrict commands to the authorized user."""
    async def predicate(ctx):
        uid = ctx.author.id if hasattr(ctx, "author") else ctx.user.id
        if uid != config.AUTHORIZED_USER_ID:
            await ctx.send("You are not authorized to use this bot.")
            logger.warning(f"Unauthorized access attempt by {uid}")
            return False
        return True
    return commands.check(predicate)
