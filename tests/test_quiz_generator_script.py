import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from scripts import test_quiz_generator as quiz_script


def test_main_list_due_initializes_databases(monkeypatch):
    init_databases = Mock()
    list_due = Mock()

    monkeypatch.setattr(quiz_script.db, "init_databases", init_databases)
    monkeypatch.setattr(quiz_script, "list_due", list_due)
    monkeypatch.setattr(sys, "argv", ["test_quiz_generator.py", "--list-due"])

    quiz_script.main()

    init_databases.assert_called_once_with()
    list_due.assert_called_once_with()


def test_main_without_args_uses_top_due_concept(monkeypatch):
    init_databases = Mock()
    resolve_concept_id = Mock(return_value=42)
    show_context = Mock()

    class _PersonaOverride:
        def __enter__(self):
            return "mentor"

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(quiz_script.db, "init_databases", init_databases)
    monkeypatch.setattr(quiz_script, "resolve_concept_id", resolve_concept_id)
    monkeypatch.setattr(quiz_script, "show_context", show_context)
    monkeypatch.setattr(quiz_script, "with_persona_override", lambda _persona: _PersonaOverride())
    monkeypatch.setattr(sys, "argv", ["test_quiz_generator.py"])

    quiz_script.main()

    init_databases.assert_called_once_with()
    resolve_concept_id.assert_called_once_with(None)
    show_context.assert_called_once_with(42)


def test_resolve_concept_id_returns_none_when_nothing_due(monkeypatch, capsys):
    monkeypatch.setattr(quiz_script.db, "get_due_concepts", Mock(return_value=[]))

    concept_id = quiz_script.resolve_concept_id(None)

    captured = capsys.readouterr()
    assert concept_id is None
    assert "No concepts due for review" in captured.out


def test_main_runs_async_flags_and_writes_log(monkeypatch):
    init_databases = Mock()
    resolve_concept_id = Mock(return_value=42)
    show_context = Mock(return_value="context text")
    run_p1 = AsyncMock(
        side_effect=[
            {
                "question": "Q1",
                "formatted_question": "FQ1",
                "difficulty": 40,
                "question_type": "definition",
                "target_facet": "facet",
                "reasoning": "Because",
                "concept_ids": [42],
                "choices": None,
            },
            {
                "question": "Q2",
                "formatted_question": "FQ2",
                "difficulty": 50,
                "question_type": "definition",
                "target_facet": "facet",
                "reasoning": "Because",
                "concept_ids": [42],
                "choices": None,
            },
        ]
    )
    run_p2 = AsyncMock(return_value="p2 output")
    run_format = AsyncMock(return_value="deterministic output")
    validate_p1_result = Mock(return_value={"question": "PASS: ok"})
    print_validation = Mock(return_value=True)
    captured_payload = {}

    class _PersonaOverride:
        def __enter__(self):
            return "mentor"

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_write_log(payload):
        captured_payload.update(payload)
        return Path("scripts/prompt_logs/test.json")

    monkeypatch.setattr(quiz_script.db, "init_databases", init_databases)
    monkeypatch.setattr(quiz_script, "resolve_concept_id", resolve_concept_id)
    monkeypatch.setattr(quiz_script, "show_context", show_context)
    monkeypatch.setattr(quiz_script, "run_p1", run_p1)
    monkeypatch.setattr(quiz_script, "run_p2", run_p2)
    monkeypatch.setattr(quiz_script, "run_format_quiz_action", run_format)
    monkeypatch.setattr(quiz_script, "validate_p1_result", validate_p1_result)
    monkeypatch.setattr(quiz_script, "print_validation", print_validation)
    monkeypatch.setattr(quiz_script, "write_log", fake_write_log)
    monkeypatch.setattr(quiz_script, "with_persona_override", lambda _persona: _PersonaOverride())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "test_quiz_generator.py",
            "42",
            "--p2",
            "--compare-p2",
            "--validate",
            "--log",
            "--repeat",
            "2",
        ],
    )

    quiz_script.main()

    init_databases.assert_called_once_with()
    resolve_concept_id.assert_called_once_with(42)
    show_context.assert_called_once_with(42)
    assert run_p1.await_count == 2
    run_p2.assert_awaited_once()
    run_format.assert_awaited_once()
    assert validate_p1_result.call_count == 2
    assert print_validation.call_count == 2
    assert captured_payload["concept_id"] == 42
    assert captured_payload["persona"] == "mentor"
    assert len(captured_payload["runs"]) == 2
    assert captured_payload["comparison"] == {
        "p2": "p2 output",
        "deterministic": "deterministic output",
    }


def test_main_rejects_nonpositive_repeat(monkeypatch):
    monkeypatch.setattr(quiz_script.db, "init_databases", Mock())
    monkeypatch.setattr(quiz_script, "resolve_concept_id", Mock(return_value=42))
    monkeypatch.setattr(sys, "argv", ["test_quiz_generator.py", "42", "--repeat", "0"])

    with pytest.raises(SystemExit):
        quiz_script.main()
