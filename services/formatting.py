"""
Discord message length utilities.

Discord enforces a hard 2000-character limit on message content.
These helpers ensure content stays within that limit when editing
or appending to existing messages.

Convention:
- config.MAX_MESSAGE_LENGTH (1900) — conservative buffer for *initial* sends.
  Leaves room for Discord's own formatting/metadata overhead.
- DISCORD_CHAR_LIMIT (2000) — hard limit used for *edits* and *append* flows
  where every character counts (e.g. appending "✅ Added" to an existing msg).

See DEVNOTES.md §8 for full context.
"""

# Discord's absolute hard limit for message content
DISCORD_CHAR_LIMIT = 2000


def truncate_for_discord(text: str | None, max_len: int = DISCORD_CHAR_LIMIT) -> str:
    """Truncate text to fit within Discord's character limit.

    Returns the text unchanged if within limits, otherwise truncates
    and appends '…' (single Unicode ellipsis character).
    """
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def truncate_with_suffix(
    original: str | None,
    suffix: str,
    max_len: int = DISCORD_CHAR_LIMIT,
) -> str:
    """Combine original + suffix, truncating to stay within max_len.

    Truncates *original* first to preserve the suffix (status notes like
    "✅ Concept added..." are more important than the tail of a long answer).
    If suffix alone exceeds max_len, truncates suffix too.
    """
    original = original or ""
    combined = original + suffix

    if len(combined) <= max_len:
        return combined

    # If suffix alone is too long, just truncate the whole thing
    if len(suffix) >= max_len:
        return suffix[: max_len - 1] + "…"

    # Truncate original to make room for suffix + ellipsis
    available = max_len - len(suffix) - 1  # -1 for the '…'
    return original[:available] + "…" + suffix


def format_quiz_metadata(concept: dict | None) -> str:
    """Return a compact metadata line for a quiz question message.

    Shows concept title, mastery score, and which review number this is.
    For the first two reviews (before the skip button unlocks), appends a
    hint explaining when the skip button will appear.

    Returns an empty string when concept is None so callers can safely
    use ``f"\\n\\n{meta}" if meta else ""`` without special-casing.
    """
    if not concept:
        return ""
    title = concept.get("title") or "?"
    mastery = concept.get("mastery_level", 0) if concept.get("mastery_level") is not None else 0
    count = concept.get("review_count", 0) if concept.get("review_count") is not None else 0
    line = f"📖 **{title}** · Score: {mastery}/100 · Review #{count + 1}"
    if count < 2:
        remaining = 2 - count
        line += f"\n_(skip unlocks after {remaining} more review(s))_"
    return line
