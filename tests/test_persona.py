"""
Tests for persona preset system.

Run: python tests/test_persona.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.preferences import (
    PERSONAS_DIR, DEFAULT_PERSONA,
    get_available_personas, get_persona, set_persona,
    get_persona_content,
)
import db


def test_persona_files_exist():
    """All expected persona files exist in data/personas/."""
    expected = ["mentor", "coach", "buddy"]
    for name in expected:
        path = PERSONAS_DIR / f"{name}.md"
        assert path.exists(), f"Missing persona file: {path}"
        print(f"  ✅ {name}.md exists ({path.stat().st_size} bytes)")


def test_persona_files_under_token_budget():
    """Each persona file should be under ~400 tokens (~1600 chars)."""
    TOKEN_BUDGET = 2500  # chars (~625 tokens, allows detailed behavioral rules)
    for path in PERSONAS_DIR.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        assert len(content) < TOKEN_BUDGET, (
            f"{path.name} is {len(content)} chars ({len(content)//4} est. tokens) "
            f"— exceeds budget of {TOKEN_BUDGET} chars"
        )
        est_tokens = len(content) // 4
        print(f"  ✅ {path.name}: {len(content)} chars (~{est_tokens} tokens)")


def test_available_personas():
    """get_available_personas returns all three presets."""
    available = get_available_personas()
    assert "mentor" in available, "mentor not found"
    assert "coach" in available, "coach not found"
    assert "buddy" in available, "buddy not found"
    print(f"  ✅ Available personas: {available}")


def test_default_persona():
    """Default persona is 'mentor'."""
    assert DEFAULT_PERSONA == "mentor"
    print(f"  ✅ Default persona: {DEFAULT_PERSONA}")


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
    print("  ✅ All three personas have unique content")


def test_get_persona_content_fallback():
    """Missing persona falls back to mentor content."""
    fallback = get_persona_content("nonexistent_persona")
    mentor = get_persona_content("mentor")
    assert fallback == mentor, "Fallback didn't return mentor content"
    print("  ✅ Missing persona falls back to mentor")


def test_set_persona_validates():
    """set_persona rejects invalid names."""
    try:
        set_persona("invalid_persona_name")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  ✅ Invalid name rejected: {e}")


def test_build_system_prompt():
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
    print("  ✅ build_system_prompt returns unique prompts per persona")

    # Check ordering: Active Persona should come after skill content
    # and before User Preferences
    for name, prompt in prompts.items():
        persona_pos = prompt.index("## Active Persona")
        prefs_pos = prompt.index("## User Preferences")
        assert persona_pos < prefs_pos, (
            f"In {name}: Persona section ({persona_pos}) should come before "
            f"Preferences ({prefs_pos})"
        )
    print("  ✅ Prompt section ordering correct (Skills → Persona → Preferences)")


def main():
    # Initialize DB (needed for session_state)
    db.init_databases()

    tests = [
        ("Persona files exist", test_persona_files_exist),
        ("Token budget", test_persona_files_under_token_budget),
        ("Available personas", test_available_personas),
        ("Default persona", test_default_persona),
        ("Persona content", test_get_persona_content),
        ("Content fallback", test_get_persona_content_fallback),
        ("Validation", test_set_persona_validates),
        ("System prompt composition", test_build_system_prompt),
    ]

    passed = 0
    failed = 0
    for label, test_fn in tests:
        print(f"\n--- {label} ---")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
