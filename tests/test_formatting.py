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
    @pytest.mark.parametrize(
        ("text", "max_len", "expected"),
        [
            ("hello", DISCORD_CHAR_LIMIT, "hello"),
            ("x" * DISCORD_CHAR_LIMIT, DISCORD_CHAR_LIMIT, "x" * DISCORD_CHAR_LIMIT),
            (
                "x" * (DISCORD_CHAR_LIMIT + 100),
                DISCORD_CHAR_LIMIT,
                "x" * (DISCORD_CHAR_LIMIT - 1) + "…",
            ),
            (None, DISCORD_CHAR_LIMIT, ""),
            ("", DISCORD_CHAR_LIMIT, ""),
            ("a" * 50, 20, "a" * 19 + "…"),
        ],
        ids=["short", "exact-limit", "over-limit", "none", "empty", "custom-limit"],
    )
    def test_cases(self, text, max_len, expected):
        assert truncate_for_discord(text, max_len=max_len) == expected


# ============================================================================
# truncate_with_suffix
# ============================================================================


class TestTruncateWithSuffix:
    @pytest.mark.parametrize(
        ("original", "suffix", "max_len", "expected", "contains_ellipsis"),
        [
            ("short original", "\n\n✅ ok", DISCORD_CHAR_LIMIT, "short original\n\n✅ ok", False),
            ("hi", "y" * 2500, DISCORD_CHAR_LIMIT, None, True),
            ("hello", "s" * DISCORD_CHAR_LIMIT, DISCORD_CHAR_LIMIT, None, False),
            (None, "\n\n✅ ok", DISCORD_CHAR_LIMIT, "\n\n✅ ok", False),
            ("", "\n\n✅ ok", DISCORD_CHAR_LIMIT, "\n\n✅ ok", False),
            ("abc", "def", 100, "abcdef", False),
            ("a" * 50, "XYZ", 30, None, True),
        ],
        ids=[
            "within-limit",
            "huge-suffix",
            "suffix-at-limit",
            "none-original",
            "empty-original",
            "no-truncation",
            "custom-limit",
        ],
    )
    def test_table_driven_cases(self, original, suffix, max_len, expected, contains_ellipsis):
        result = truncate_with_suffix(original, suffix, max_len=max_len)

        if expected is not None:
            assert result == expected
        assert len(result) <= max_len
        if contains_ellipsis:
            assert "…" in result

        if original == "":
            assert not result.startswith("…")

        if suffix:
            if len(suffix) < max_len:
                assert result.endswith(suffix)
            else:
                assert result.endswith("…")

    @pytest.mark.parametrize(
        ("original", "suffix", "contains_ellipsis"),
        [
            ("x" * 1970, "\n\n✅ Concept 'Something Long' added under Topic.", True),
            ("x" * 1980, "\n\n✅ Done", False),
            (
                "x" * 1900,
                (
                    "\n\n✅ Concept 'Chromium oxide passivation' added under "
                    "Stainless Steel and Corrosion Engineering. First review tomorrow."
                ),
                True,
            ),
        ],
        ids=["over-limit", "suffix-preserved", "realistic-add-concept"],
    )
    def test_suffix_preservation_cases(self, original, suffix, contains_ellipsis):
        result = truncate_with_suffix(original, suffix)
        assert len(result) <= DISCORD_CHAR_LIMIT
        assert result.endswith(suffix)
        if contains_ellipsis:
            assert "…" in result
        else:
            assert "…" not in result
