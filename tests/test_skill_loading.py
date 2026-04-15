"""Tests for modular skill loading and prompt composition."""

import pytest

from services.pipeline import (
    SKILL_SETS,
    SKILLS_DIR,
    _get_base_prompt,
    _mode_to_skill_set,
    build_system_prompt,
    invalidate_prompt_cache,
)


@pytest.fixture(autouse=True)
def _isolated_prompt_db(test_db):
    """Initialize prompt-building tests against the shared isolated DB fixture."""
    return test_db


# ── Skill file structure ──────────────────────────────────────────────


def test_skill_files_exist():
    """All expected skill files exist in data/skills/."""
    expected = ["core", "quiz", "knowledge", "maintenance"]
    for name in expected:
        path = SKILLS_DIR / f"{name}.md"
        assert path.exists(), f"Missing skill file: {path}"


def test_skill_files_have_content():
    """Each skill file is non-empty and has reasonable size."""
    for name in ["core", "quiz", "knowledge", "maintenance"]:
        path = SKILLS_DIR / f"{name}.md"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, f"{name}.md is suspiciously small ({len(content)} chars)"


def test_core_has_do_not_remove_markers():
    """core.md should NOT have DO NOT REMOVE markers — those are in quiz/knowledge."""
    content = (SKILLS_DIR / "core.md").read_text(encoding="utf-8")
    assert "<!-- DO NOT REMOVE" not in content, "core.md should not contain DO NOT REMOVE markers"


def test_quiz_has_critical_examples():
    """quiz.md must contain DO NOT REMOVE markers for quiz and assess examples."""
    content = (SKILLS_DIR / "quiz.md").read_text(encoding="utf-8")
    assert content.count("<!-- DO NOT REMOVE") >= 2, (
        "quiz.md must have at least 2 DO NOT REMOVE markers (quiz + assess)"
    )
    assert '"action": "quiz"' in content, "quiz.md must have quiz JSON example"
    assert '"action": "assess"' in content, "quiz.md must have assess JSON example"


def test_knowledge_has_critical_examples():
    """knowledge.md must contain DO NOT REMOVE markers for add_concept and suggest_topic."""
    content = (SKILLS_DIR / "knowledge.md").read_text(encoding="utf-8")
    assert content.count("<!-- DO NOT REMOVE") >= 2, (
        "knowledge.md must have at least 2 DO NOT REMOVE markers"
    )
    assert '"action": "add_concept"' in content or '"action":"add_concept"' in content
    assert '"action": "suggest_topic"' in content or '"action":"suggest_topic"' in content


# ── Mode to skill set mapping ─────────────────────────────────────────


def test_mode_to_skill_set_command():
    assert _mode_to_skill_set("command") == "interactive"


def test_mode_to_skill_set_reply():
    assert _mode_to_skill_set("reply") == "interactive"


def test_mode_to_skill_set_review():
    assert _mode_to_skill_set("review-check") == "review"


def test_mode_to_skill_set_maintenance():
    assert _mode_to_skill_set("maintenance") == "maintenance"


def test_mode_to_skill_set_unknown_falls_back():
    """Unknown mode defaults to interactive."""
    assert _mode_to_skill_set("bogus") == "interactive"


# ── Skill set definitions ─────────────────────────────────────────────


def test_skill_sets_structure():
    """SKILL_SETS has the expected entries."""
    assert set(SKILL_SETS.keys()) == {
        "interactive",
        "review",
        "maintenance",
        "quiz-packaging",
        "taxonomy",
        "preference-edit",
    }


def test_core_in_all_skill_sets():
    """core.md is loaded for every skill set except self-contained agents."""
    # These skill sets are intentionally isolated and don't use core.
    no_core_sets = {"taxonomy", "preference-edit"}
    for name, skills in SKILL_SETS.items():
        if name in no_core_sets:
            assert "core" not in skills, f"{name} skill set should not include core"
        else:
            assert "core" in skills, f"core missing from skill set '{name}'"


def test_interactive_has_quiz_and_knowledge():
    assert "quiz" in SKILL_SETS["interactive"]
    assert "knowledge" in SKILL_SETS["interactive"]


def test_review_has_quiz_no_knowledge():
    assert "quiz" in SKILL_SETS["review"]
    assert "knowledge" not in SKILL_SETS["review"]


def test_maintenance_has_knowledge_and_maintenance():
    assert "maintenance" in SKILL_SETS["maintenance"]
    assert "knowledge" in SKILL_SETS["maintenance"]
    assert "quiz" not in SKILL_SETS["maintenance"]


# ── Conditional loading produces different prompts ─────────────────────


def test_different_skill_sets_produce_different_prompts():
    """build_system_prompt for different modes returns different content."""
    invalidate_prompt_cache()

    interactive_prompt = build_system_prompt("mentor", mode="command")
    review_prompt = build_system_prompt("mentor", mode="review-check")
    maintenance_prompt = build_system_prompt("mentor", mode="maintenance")

    # They should all be different (different skill files loaded)
    assert interactive_prompt != review_prompt, "interactive and review prompts should differ"
    assert interactive_prompt != maintenance_prompt, (
        "interactive and maintenance prompts should differ"
    )
    assert review_prompt != maintenance_prompt, "review and maintenance prompts should differ"


def test_interactive_prompt_has_quiz_and_knowledge_content():
    """Interactive mode prompt includes content from both quiz.md and knowledge.md."""
    invalidate_prompt_cache()

    prompt = build_system_prompt("mentor", mode="command")
    assert "assess" in prompt.lower(), "Interactive prompt should contain assess content"
    assert "add_concept" in prompt.lower() or "add_topic" in prompt.lower(), (
        "Interactive prompt should contain knowledge CRUD content"
    )


def test_review_prompt_has_quiz_no_knowledge_crud():
    """Review mode prompt includes quiz but not knowledge action definitions."""
    invalidate_prompt_cache()

    prompt = build_system_prompt("mentor", mode="review-check")
    assert "assess" in prompt.lower(), "Review prompt should contain assess content"
    # Full knowledge action sections (with parameter docs) should NOT be present.
    # Core.md may reference suggest_topic/add_concept in mode descriptions and rules,
    # but the detailed action definitions with parameters are in knowledge.md.
    assert "### add_topic" not in prompt, (
        "Review prompt should NOT contain add_topic action definition"
    )
    assert "### add_concept" not in prompt, (
        "Review prompt should NOT contain add_concept action definition"
    )
    assert "### suggest_topic" not in prompt, (
        "Review prompt should NOT contain suggest_topic action definition"
    )


def test_maintenance_prompt_has_maintenance_rules():
    """Maintenance mode prompt includes maintenance rules."""
    invalidate_prompt_cache()

    prompt = build_system_prompt("mentor", mode="maintenance")
    # Maintenance rules should be present
    assert "maintenance" in prompt.lower()
    # Quiz actions should NOT be present
    assert '"action": "quiz"' not in prompt, (
        "Maintenance prompt should NOT contain quiz action example"
    )


def test_command_and_reply_produce_same_prompt():
    """COMMAND and REPLY modes use the same interactive skill set."""
    invalidate_prompt_cache()

    command_prompt = build_system_prompt("mentor", mode="command")
    reply_prompt = build_system_prompt("mentor", mode="reply")
    assert command_prompt == reply_prompt, (
        "command and reply should produce identical prompts (same skill set)"
    )


# ── Cache behavior ────────────────────────────────────────────────────


def test_cache_returns_same_object_on_repeated_calls():
    """Consecutive calls with same params return cached result."""
    invalidate_prompt_cache()

    p1 = build_system_prompt("mentor", mode="command")
    p2 = build_system_prompt("mentor", mode="command")
    assert p1 == p2


def test_invalidate_clears_cache():
    """After invalidation, the prompt is rebuilt."""
    invalidate_prompt_cache()

    p1 = build_system_prompt("mentor", mode="command")
    invalidate_prompt_cache()
    p2 = build_system_prompt("mentor", mode="command")
    # Content should be the same (files haven't changed)
    assert p1 == p2


# ── Base prompt per skill set ─────────────────────────────────────────


def test_base_prompt_interactive_vs_review():
    """_get_base_prompt returns different content for interactive vs review."""
    invalidate_prompt_cache()

    interactive = _get_base_prompt("interactive")
    review = _get_base_prompt("review")
    assert interactive != review, "interactive and review base prompts should differ"
    assert len(interactive) > len(review), (
        "interactive base prompt should be larger (has more skills)"
    )
