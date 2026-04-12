import sys
from unittest.mock import Mock

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

    monkeypatch.setattr(quiz_script.db, "init_databases", init_databases)
    monkeypatch.setattr(quiz_script, "resolve_concept_id", resolve_concept_id)
    monkeypatch.setattr(quiz_script, "show_context", show_context)
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