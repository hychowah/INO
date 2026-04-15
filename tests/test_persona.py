"""Tests for the persona preset system."""

import pytest

from db.preferences import (
    DEFAULT_PERSONA,
    PERSONAS_DIR,
    get_available_personas,
    get_persona_content,
    set_persona,
)


def test_persona_files_exist():
    """All expected persona files exist in data/personas/."""
    expected = ["mentor", "coach", "buddy"]
    for name in expected:
        path = PERSONAS_DIR / f"{name}.md"
        assert path.exists(), f"Missing persona file: {path}"


def test_persona_files_under_token_budget():
    """Each persona file should be under ~750 tokens (~3000 chars)."""
    TOKEN_BUDGET = 3000  # chars (~750 tokens, allows detailed behavioral rules)
    for path in PERSONAS_DIR.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert len(content) < TOKEN_BUDGET, (
            f"{path.name} is {len(content)} chars ({len(content) // 4} est. tokens) "
            f"— exceeds budget of {TOKEN_BUDGET} chars"
        )


def test_available_personas():
    """get_available_personas returns all three presets."""
    available = get_available_personas()
    assert "mentor" in available, "mentor not found"
    assert "coach" in available, "coach not found"
    assert "buddy" in available, "buddy not found"


def test_default_persona():
    """Default persona is 'mentor'."""
    assert DEFAULT_PERSONA == "mentor"


def test_get_persona_content():
    """Each persona returns different content."""
    contents = {}
    for name in ["mentor", "coach", "buddy"]:
        content = get_persona_content(name)
        assert content, f"Empty content for persona '{name}'"
        assert name.title() in content or name in content.lower(), (
            f"Persona file for '{name}' doesn't seem to reference its own name"
        )
        contents[name] = content

    # Verify they're actually different
    assert contents["mentor"] != contents["coach"], "mentor == coach"
    assert contents["coach"] != contents["buddy"], "coach == buddy"
    assert contents["mentor"] != contents["buddy"], "mentor == buddy"


def test_get_persona_content_fallback():
    """Missing persona falls back to mentor content."""
    fallback = get_persona_content("nonexistent_persona")
    mentor = get_persona_content("mentor")
    assert fallback == mentor, "Fallback didn't return mentor content"


def test_set_persona_validates():
    """set_persona rejects invalid names."""
    with pytest.raises(ValueError):
        set_persona("invalid_persona_name")


def test_build_system_prompt(test_db):
    """build_system_prompt returns different content per persona."""
    from services.pipeline import build_system_prompt

    prompts = {}
    for name in ["mentor", "coach", "buddy"]:
        prompt = build_system_prompt(name, mode="command")
        assert "## Active Persona" in prompt, f"Persona section missing for '{name}'"
        assert "## User Preferences" in prompt, f"Preferences section missing for '{name}'"
        prompts[name] = prompt

    # Verify different
    assert prompts["mentor"] != prompts["coach"], "mentor prompt == coach prompt"
    assert prompts["coach"] != prompts["buddy"], "coach prompt == buddy prompt"

    # Check ordering: Active Persona should come after skill content
    # and before User Preferences
    for name, prompt in prompts.items():
        persona_pos = prompt.index("## Active Persona")
        prefs_pos = prompt.index("## User Preferences")
        assert persona_pos < prefs_pos, (
            f"In {name}: Persona section ({persona_pos}) should come before "
            f"Preferences ({prefs_pos})"
        )
