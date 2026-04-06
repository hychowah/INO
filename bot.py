#!/usr/bin/env python3
"""
Thin entry point — run with: python bot.py
All bot logic lives in the bot/ package.
"""

import io
import logging
import os
import sys
from pathlib import Path

# Fix Windows console encoding before anything else
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Load .env early so LOG_LEVEL (and other vars) are available before config import
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

_log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
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

import discord  # noqa: E402

import config  # noqa: E402

# Import the bot package — registers all commands and event handlers
from bot import bot  # noqa: E402,F401


def main():
    errors = config.validate_config()
    if errors:
        logger.error("CONFIGURATION ERRORS:")
        for e in errors:
            logger.error(f"  * {e}")
        sys.exit(1)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(
        f"Starting learning bot... data dir: {config.DATA_DIR} "
        f"[log level: {logging.getLevelName(_log_level)}]"
    )

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
