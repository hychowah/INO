"""Tests for services.formatting — Discord message truncation helpers."""

import pytest

from services.formatting import (
    DISCORD_CHAR_LIMIT,
    truncate_for_discord,
    truncate_with_suffix,
)

pytestmark = pytest.mark.unit

# ============================================================================
# truncate_for_discord
# ============================================================================


class TestTruncateForDiscord:
    def test_short_text_unchanged(self):
        assert truncate_for_discord("hello") == "hello"

    def test_exact_limit_unchanged(self):
        text = "x" * DISCORD_CHAR_LIMIT
        assert truncate_for_discord(text) == text

    def test_over_limit_truncated(self):
        text = "x" * (DISCORD_CHAR_LIMIT + 100)
        result = truncate_for_discord(text)
        assert len(result) == DISCORD_CHAR_LIMIT
        assert result.endswith("…")

    def test_none_returns_empty(self):
        assert truncate_for_discord(None) == ""

    def test_empty_string_returns_empty(self):
        assert truncate_for_discord("") == ""

    def test_custom_max_len(self):
        result = truncate_for_discord("a" * 50, max_len=20)
        assert len(result) == 20
        assert result.endswith("…")
        assert result == "a" * 19 + "…"


# ============================================================================
# truncate_with_suffix
# ============================================================================


class TestTruncateWithSuffix:
    def test_within_limit_unchanged(self):
        result = truncate_with_suffix("short original", "\n\n✅ ok")
        assert result == "short original\n\n✅ ok"

    def test_over_limit_truncates_original(self):
        original = "x" * 1970
        suffix = "\n\n✅ Concept 'Something Long' added under Topic."
        result = truncate_with_suffix(original, suffix)
        assert len(result) <= DISCORD_CHAR_LIMIT
        assert result.endswith(suffix)
        assert "…" in result

    def test_suffix_preserved_exactly(self):
        original = "x" * 1980
        suffix = "\n\n✅ Done"
        result = truncate_with_suffix(original, suffix)
        assert result.endswith(suffix)
        assert len(result) <= DISCORD_CHAR_LIMIT

    def test_huge_suffix_alone(self):
        """If suffix alone exceeds limit, truncate the suffix."""
        result = truncate_with_suffix("hi", "y" * 2500)
        assert len(result) <= DISCORD_CHAR_LIMIT
        assert result.endswith("…")

    def test_suffix_exactly_at_limit(self):
        """Suffix exactly at limit — original must be dropped entirely."""
        suffix = "s" * DISCORD_CHAR_LIMIT
        result = truncate_with_suffix("hello", suffix)
        assert len(result) <= DISCORD_CHAR_LIMIT

    def test_none_original(self):
        result = truncate_with_suffix(None, "\n\n✅ ok")
        assert result == "\n\n✅ ok"

    def test_empty_original(self):
        """Empty original should not produce a leading ellipsis."""
        result = truncate_with_suffix("", "\n\n✅ ok")
        assert result == "\n\n✅ ok"
        assert not result.startswith("…")

    def test_no_truncation_needed(self):
        result = truncate_with_suffix("abc", "def", max_len=100)
        assert result == "abcdef"

    def test_custom_max_len(self):
        result = truncate_with_suffix("a" * 50, "XYZ", max_len=30)
        assert len(result) <= 30
        assert result.endswith("XYZ")
        assert "…" in result

    def test_realistic_add_concept_scenario(self):
        """Simulate the actual crash scenario: 1900-char LLM answer + 120-char note."""
        original = "x" * 1900
        note = (
            "\n\n\u2705 Concept 'Chromium oxide passivation' added under "
            "Stainless Steel and Corrosion Engineering. First review tomorrow."
        )
        result = truncate_with_suffix(original, note)
        assert len(result) <= DISCORD_CHAR_LIMIT
        assert result.endswith(note)
        assert "…" in result
