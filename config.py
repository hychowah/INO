#!/usr/bin/env python3
"""
Configuration for the Learning Agent Discord Bot.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass  # python-dotenv not installed — rely on actual env vars

# ============================================================================
# REQUIRED SETTINGS
# ============================================================================

# Discord Bot Token — get a SEPARATE token for this bot
# Create a new application at https://discord.com/developers/applications
BOT_TOKEN = os.environ.get("LEARN_BOT_TOKEN", "")

# Your Discord User ID — set via env var or replace this default
AUTHORIZED_USER_ID = int(os.environ.get("LEARN_AUTHORIZED_USER_ID", "0"))

# ============================================================================
# API SETTINGS (FastAPI backend for mobile app)
# ============================================================================

API_HOST = os.environ.get("LEARN_API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("LEARN_API_PORT", "8080"))
API_SECRET_KEY = os.environ.get("LEARN_API_SECRET_KEY", "")

# ============================================================================
# OPTIONAL SETTINGS
# ============================================================================

# Working directory (learning_agent root)
BASE_DIR = Path(__file__).parent.resolve()

# Data directory
DATA_DIR = BASE_DIR / "data"

# Instruction file paths (centralized — do not redefine in service modules)
SKILLS_DIR = DATA_DIR / "skills"
PERSONAS_DIR = DATA_DIR / "personas"
PREFERENCES_MD = DATA_DIR / "preferences.md"
PREFERENCES_TEMPLATE_MD = DATA_DIR / "preferences.template.md"

# Max Discord message length
MAX_MESSAGE_LENGTH = 1900

# Default timeout for LLM calls (seconds)
COMMAND_TIMEOUT = 120

# Review scheduler interval (minutes)
REVIEW_CHECK_INTERVAL_MINUTES = 15

# Maintenance and background scheduler intervals (hours)
MAINTENANCE_MODE_ENABLED = os.environ.get("LEARN_ENABLE_MAINTENANCE", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DEDUP_MODE_ENABLED = os.environ.get("LEARN_ENABLE_DEDUP", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
MAINTENANCE_INTERVAL_HOURS = max(1, int(os.environ.get("LEARN_MAINTENANCE_INTERVAL_HOURS", "168")))
TAXONOMY_INTERVAL_HOURS = max(1, int(os.environ.get("LEARN_TAXONOMY_INTERVAL_HOURS", "168")))
DEDUP_INTERVAL_HOURS = max(1, int(os.environ.get("LEARN_DEDUP_INTERVAL_HOURS", "168")))
BACKUP_INTERVAL_HOURS = max(1, int(os.environ.get("LEARN_BACKUP_INTERVAL_HOURS", "24")))
PROPOSAL_CLEANUP_INTERVAL_HOURS = max(
    1, int(os.environ.get("LEARN_PROPOSAL_CLEANUP_INTERVAL_HOURS", "24"))
)

# Session timeout (minutes of inactivity before session auto-ends)
SESSION_TIMEOUT_MINUTES = 15

# Review nag cooldown — don't re-send the same concept within this many hours
REVIEW_NAG_COOLDOWN_HOURS = int(os.environ.get("LEARN_REVIEW_NAG_COOLDOWN_HOURS", "2"))

# Quiet hours for scheduled review reminders (local wall clock in UTC+8)
REVIEW_QUIET_HOURS_START_HOUR = int(os.environ.get("LEARN_REVIEW_QUIET_HOURS_START_HOUR", "23"))
REVIEW_QUIET_HOURS_END_HOUR = int(os.environ.get("LEARN_REVIEW_QUIET_HOURS_END_HOUR", "7"))

# Quiz staleness timeout — auto-clear active quiz context after this many
# minutes of inactivity.  Excludes REVIEW-CHECK mode (intentional quizzes).
QUIZ_STALENESS_TIMEOUT_MINUTES = int(os.environ.get("LEARN_QUIZ_STALENESS_TIMEOUT", "15"))

# Max reminders for an unanswered review before moving on to the next concept
REVIEW_REMINDER_MAX = int(os.environ.get("LEARN_REVIEW_REMINDER_MAX", "3"))

# Graph visualization — max concept nodes before filtering
MAX_GRAPH_NODES = int(os.environ.get("LEARN_MAX_GRAPH_NODES", "500"))

# Spaced repetition interval exponent.
# Interval formula: interval_days = exp(mastery_score * SR_INTERVAL_EXPONENT)
# At 0.075: score=50 → ~43 days, score=100 → ~1808 days.
# Only affects NEW reviews; existing interval_days values are unchanged.
SR_INTERVAL_EXPONENT = float(os.environ.get("LEARN_SR_INTERVAL_EXPONENT", "0.075"))

# ============================================================================
# BACKUP SETTINGS
# ============================================================================

# Directory where timestamped backup snapshots are stored
BACKUP_DIR = Path(os.environ.get("LEARN_BACKUP_DIR", str(BASE_DIR / "backups")))

# Number of daily backups to retain before pruning (minimum 1 enforced)
BACKUP_RETENTION_DAYS = max(1, int(os.environ.get("LEARN_BACKUP_RETENTION_DAYS", "14")))

# ============================================================================
# VECTOR STORE SETTINGS (hybrid search)
# ============================================================================

# Path to Qdrant embedded storage (alongside SQLite databases)
VECTOR_STORE_PATH = Path(
    os.environ.get("LEARN_VECTOR_STORE_PATH", str(BASE_DIR / "data" / "vectors"))
)

# Sentence-transformers model for embeddings
EMBEDDING_MODEL = os.environ.get("LEARN_EMBEDDING_MODEL", "all-mpnet-base-v2")

# Default search limit for vector queries
VECTOR_SEARCH_LIMIT = int(os.environ.get("LEARN_VECTOR_SEARCH_LIMIT", "10"))

# Similarity thresholds (cosine similarity, 0.0–1.0)
SIMILARITY_THRESHOLD_DEDUP = float(os.environ.get("LEARN_SIM_DEDUP", "0.92"))
SIMILARITY_THRESHOLD_RELATION = float(os.environ.get("LEARN_SIM_RELATION", "0.5"))

# ============================================================================
# LLM PROVIDER SETTINGS
# ============================================================================

# Provider: "openai_compat" (Grok, DeepSeek, OpenAI, …)
LLM_PROVIDER = os.environ.get("LEARN_LLM_PROVIDER", "openai_compat")

# --- OpenAI-compatible backend ---
# Required when LLM_PROVIDER = "openai_compat"
# Examples:
#   Grok:     https://api.x.ai/v1
#   DeepSeek: https://api.deepseek.com
LLM_API_BASE_URL = os.environ.get("LEARN_LLM_BASE_URL")
LLM_API_KEY = os.environ.get("LEARN_LLM_API_KEY")
LLM_MODEL = os.environ.get("LEARN_LLM_MODEL")  # e.g. "grok-3", "deepseek-chat"
LLM_TEMPERATURE = (
    float(os.environ["LEARN_LLM_TEMPERATURE"]) if os.environ.get("LEARN_LLM_TEMPERATURE") else None
)
LLM_MAX_TOKENS = (
    int(os.environ["LEARN_LLM_MAX_TOKENS"]) if os.environ.get("LEARN_LLM_MAX_TOKENS") else 4096
)
LLM_MAX_HISTORY_TOKENS = int(os.environ.get("LEARN_LLM_MAX_HISTORY_TOKENS", "40000"))
# Thinking mode for models that support it: "enabled" | "disabled" | None
# (use model default)
LLM_THINKING = os.environ.get("LEARN_LLM_THINKING")  # e.g. "disabled"
# Main interactive output contract mode:
# - auto: prefer provider JSON mode on known-compatible endpoints, with fallback
# - json_object: request OpenAI-compatible JSON object mode
# - json_schema: request OpenAI-compatible JSON schema mode when supported
# - legacy: prompt-only text/JSON contract with deterministic validation
LLM_OUTPUT_MODE = os.environ.get("LEARN_LLM_OUTPUT_MODE", "auto").lower().strip()
LLM_FAILURE_LOG_DIR = Path(
    os.environ.get("LEARN_LLM_FAILURE_LOG_DIR", str(DATA_DIR / "llm_failures"))
)
LLM_LOG_FAILURE_RAW = os.environ.get("LEARN_LLM_LOG_FAILURE_RAW", "1").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# --- Reasoning provider (optional, for scheduled quiz question generation) ---
# If set, the reasoning model is used for Prompt 1 (question analysis/generation)
# while deterministic code handles the final delivery formatting.
# Falls back to the main provider if not configured.
REASONING_LLM_BASE_URL = os.environ.get("LEARN_REASONING_LLM_BASE_URL")
REASONING_LLM_API_KEY = os.environ.get("LEARN_REASONING_LLM_API_KEY")
REASONING_LLM_MODEL = os.environ.get("LEARN_REASONING_LLM_MODEL")
REASONING_LLM_THINKING = os.environ.get("LEARN_REASONING_LLM_THINKING")  # e.g. "enabled"


# ============================================================================
# VALIDATION
# ============================================================================


def validate_config():
    """Validate configuration. Returns list of error strings."""
    errors = []
    # BOT_TOKEN is only required for Discord bot mode, not API mode
    if not AUTHORIZED_USER_ID:
        errors.append("AUTHORIZED_USER_ID not set! Set LEARN_AUTHORIZED_USER_ID env var.")

    if LLM_PROVIDER == "openai_compat":
        if not LLM_API_BASE_URL:
            errors.append("LLM_API_BASE_URL required when LLM_PROVIDER=openai_compat")
        if not LLM_API_KEY:
            errors.append("LLM_API_KEY required when LLM_PROVIDER=openai_compat")
        if not LLM_MODEL:
            errors.append("LLM_MODEL required when LLM_PROVIDER=openai_compat")
        if LLM_OUTPUT_MODE not in {"auto", "json_object", "json_schema", "legacy"}:
            errors.append(
                "LEARN_LLM_OUTPUT_MODE must be one of: auto, json_object, json_schema, legacy "
                f"(got {LLM_OUTPUT_MODE!r})"
            )
    else:
        errors.append(f"Unknown LLM_PROVIDER: {LLM_PROVIDER!r}")

    return errors


def print_config():
    """Print config summary (no secrets)."""
    print(f"  Authorized User: {AUTHORIZED_USER_ID}")
    print(f"  Base Dir       : {BASE_DIR}")
    print(f"  Data Dir       : {DATA_DIR}")
    print(f"  LLM Provider   : {LLM_PROVIDER}")
    print(f"  LLM Model      : {LLM_MODEL}")
    print(f"  Output Mode    : {LLM_OUTPUT_MODE}")
    print(f"  LLM Base URL   : {LLM_API_BASE_URL}")
    _key = "***" + LLM_API_KEY[-4:] if LLM_API_KEY and len(LLM_API_KEY) > 4 else "(not set)"
    print(f"  LLM API Key    : {_key}")
    if REASONING_LLM_MODEL:
        print(f"  Reasoning Model: {REASONING_LLM_MODEL}")
        print(f"  Reasoning URL  : {REASONING_LLM_BASE_URL}")
    print(f"  Review Interval: {REVIEW_CHECK_INTERVAL_MINUTES} min")
    if MAINTENANCE_MODE_ENABLED:
        print(f"  Maintenance    : {MAINTENANCE_INTERVAL_HOURS} h")
    else:
        print("  Maintenance    : disabled")
    print(f"  Taxonomy       : {TAXONOMY_INTERVAL_HOURS} h")
    if DEDUP_MODE_ENABLED:
        print(f"  Dedup          : {DEDUP_INTERVAL_HOURS} h")
    else:
        print("  Dedup          : disabled")
    print(f"  Backup         : {BACKUP_INTERVAL_HOURS} h")
    print(f"  Session Timeout: {SESSION_TIMEOUT_MINUTES} min")
    print(f"  API           : http://{API_HOST}:{API_PORT}")
