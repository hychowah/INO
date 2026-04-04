#!/usr/bin/env python3
"""
Thin entry point — run with: python bot.py
All bot logic lives in the bot/ package.
"""

import sys
import io
import logging

# Fix Windows console encoding before anything else
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("discord").setLevel(logging.INFO)
logging.getLogger("discord.http").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("bot")

import discord
import config

# Import the bot package — registers all commands and event handlers
from bot import bot  # noqa: F401


def main():
    errors = config.validate_config()
    if errors:
        logger.error("CONFIGURATION ERRORS:")
        for e in errors:
            logger.error(f"  * {e}")
        sys.exit(1)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Starting learning bot... data dir: {config.DATA_DIR}")

    try:
        bot.run(config.BOT_TOKEN, log_handler=None)
    except discord.LoginFailure:
        logger.critical("Invalid Bot Token!")
    except Exception as e:
        logger.critical(f"Fatal: {e}", exc_info=True)

    if getattr(bot, "_restart_requested", False):
        logger.info("Clean exit with code 42 — process manager should restart.")
        sys.exit(42)


if __name__ == "__main__":
    main()
